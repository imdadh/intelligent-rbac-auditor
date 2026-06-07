from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import correlation_id_var
from app.models.audit import Audit
from app.models.base import get_db
from app.models.dataset import Dataset
from app.models.finding import Finding
from app.schemas.audit import AuditCreate, AuditStatusResponse
from app.schemas.common import DataResponse, Meta
from app.schemas.finding import FindingSchema
from app.services.pipeline import run_audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audits", tags=["audits"])


# ------------------------------------------------------------------
# Helper to get a database session for background tasks
# ------------------------------------------------------------------
def _get_background_db() -> Session:
    """Create a new SQLAlchemy session for use in a background task."""
    from app.models.base import SessionLocal, _ensure_session_factory_bound

    _ensure_session_factory_bound()
    return SessionLocal()


# ------------------------------------------------------------------
# Background task wrapper
# ------------------------------------------------------------------
def _run_audit_background(
    dataset_id: uuid.UUID,
    audit_id: uuid.UUID,
    dormant_threshold_days: int,
    correlation_id: str,
) -> None:
    """Execute the audit pipeline in background and update the audit record.

    This function opens and closes its own database session to avoid
    sharing the request's session.
    """
    # Propagate the correlation ID from the triggering request so that
    # log entries emitted during the background task are correlated.
    if correlation_id:
        correlation_id_var.set(correlation_id)

    db: Session = _get_background_db()
    try:
        # Instantiate the LLM provider based on configuration
        settings = get_settings()
        if settings.llm_provider == "azure_openai":
            from app.llm.azure_provider import AzureOpenAIProvider

            provider = AzureOpenAIProvider()
        else:
            from app.llm.openai_provider import OpenAIProvider

            provider = OpenAIProvider()  # type: ignore[assignment]

        run_audit(
            dataset_id=dataset_id,
            provider=provider,
            db=db,
            dormant_threshold_days=dormant_threshold_days,
            audit_id=audit_id,
        )
        db.commit()
        logger.info("Background audit %s completed successfully.", dataset_id)
    except Exception:
        logger.exception("Background audit %s failed.", dataset_id)
        db.rollback()
        # Update the audit status to 'failed' if the pipeline raised
        try:
            audit: Audit | None = db.query(Audit).filter(Audit.dataset_id == dataset_id).first()
            if audit is not None:
                audit.status = "failed"
                audit.completed_at = datetime.now(UTC)
                db.commit()
        except Exception:
            logger.exception("Failed to update audit status after pipeline failure.")
    finally:
        db.close()


# ------------------------------------------------------------------
# POST /api/v1/audits
# ------------------------------------------------------------------
@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DataResponse,
    summary="Trigger a new audit",
    description=(
        "Accepts a dataset ID, creates an audit record with status 'pending', "
        "and starts the analysis pipeline in the background. Returns immediately "
        "with the new audit's ID. Poll GET /api/v1/audits/{audit_id} for completion."
    ),
)
async def create_audit(
    payload: AuditCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),  # type: ignore[arg-type]
) -> DataResponse:
    """Create an audit and schedule background processing."""
    # Validate that the dataset exists
    dataset: Dataset | None = db.query(Dataset).filter(Dataset.id == payload.dataset_id).first()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset {payload.dataset_id} not found.",
        )

    settings = get_settings()
    dormant_threshold_days = settings.dormant_threshold_days

    # Capture the correlation ID from the current request context so it can
    # be propagated to the background task.
    correlation_id = correlation_id_var.get()

    # Create the audit record with status 'pending'
    audit = Audit(
        dataset_id=payload.dataset_id,
        status="pending",
        parameters={
            "dormant_threshold_days": dormant_threshold_days,
            "llm_provider": settings.llm_provider,
        },
        created_at=datetime.now(UTC),
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)

    # Schedule the background task, passing the correlation ID
    background_tasks.add_task(
        _run_audit_background,
        dataset_id=payload.dataset_id,
        audit_id=audit.id,
        dormant_threshold_days=dormant_threshold_days,
        correlation_id=correlation_id,
    )

    logger.info(
        "Audit %s created (pending) for dataset %s.",
        audit.id,
        payload.dataset_id,
    )

    audit_response = AuditStatusResponse(
        id=audit.id,
        dataset_id=audit.dataset_id,
        status=audit.status,
        parameters=audit.parameters,
        created_at=audit.created_at,
    )

    return DataResponse(
        data=audit_response.model_dump(mode="json"),
        meta=Meta(),
    )


# ------------------------------------------------------------------
# GET /api/v1/audits/{audit_id}
# ------------------------------------------------------------------
@router.get(
    "/{audit_id}",
    response_model=DataResponse,
    summary="Get audit status and results",
    description=(
        "Returns the current state of an audit. If the audit has completed, "
        "the response includes the full structured findings from the findings table."
    ),
)
def get_audit(
    audit_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> DataResponse:
    """Retrieve an audit by its ID, including findings if completed."""
    audit: Audit | None = db.query(Audit).filter(Audit.id == audit_id).first()
    if audit is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit {audit_id} not found.",
        )

    findings_data: list[dict] = []
    if audit.status == "completed":
        findings_orm = (
            db.query(Finding)
            .filter(Finding.audit_id == audit_id)
            .order_by(Finding.created_at.asc())
            .all()
        )
        findings_data = [
            FindingSchema.model_validate(f).model_dump(mode="json") for f in findings_orm
        ]

    data = {
        "id": str(audit.id),
        "dataset_id": str(audit.dataset_id),
        "status": audit.status,
        "parameters": audit.parameters,
        "summary": audit.summary,
        "started_at": audit.started_at.isoformat() if audit.started_at else None,
        "completed_at": audit.completed_at.isoformat() if audit.completed_at else None,
        "created_at": audit.created_at.isoformat() if audit.created_at else None,
        "findings": findings_data,
    }

    return DataResponse(
        data=data,
        meta=Meta(),
    )


# ------------------------------------------------------------------
# GET /api/v1/audits/{audit_id}/report?format=markdown
# ------------------------------------------------------------------
@router.get(
    "/{audit_id}/report",
    summary="Get audit report in Markdown format",
    description=(
        "Returns a human-readable Markdown report for a completed audit. "
        "The report includes an executive summary, findings grouped by severity, "
        "and each finding's plain-language narrative explanation. "
        "Only the 'markdown' format is supported in this phase."
    ),
)
def get_audit_report(
    audit_id: uuid.UUID,
    format: str = Query("markdown", description="Report format (only 'markdown' supported)"),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    """Generate a Markdown narrative report from the audit findings."""
    if format != "markdown":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported report format '{format}'. Only 'markdown' is available.",
        )

    audit: Audit | None = db.query(Audit).filter(Audit.id == audit_id).first()
    if audit is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit {audit_id} not found.",
        )

    if audit.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Audit {audit_id} has status '{audit.status}'. Report is only available when status is 'completed'.",
        )

    # Fetch findings ordered by creation time
    findings_orm = (
        db.query(Finding)
        .filter(Finding.audit_id == audit_id)
        .order_by(Finding.created_at.asc())
        .all()
    )

    if not findings_orm:
        # No findings – still generate a minimal report
        markdown = _generate_empty_report(audit)
    else:
        markdown = _generate_markdown_report(audit, findings_orm)

    return PlainTextResponse(
        content=markdown,
        media_type="text/markdown",
        headers={"X-Content-Type-Options": "nosniff"},
    )


def _generate_markdown_report(audit: Audit, findings: list[Finding]) -> str:
    """Build a Markdown narrative report from audit metadata and findings.

    The report includes:
    - Header with title and audit metadata
    - Executive summary (from audit.summary if present)
    - Findings grouped by severity (critical, high, medium, low)
    - Each finding includes the narrative field (stored from LLM analysis)
    """
    lines: list[str] = []

    # Title and metadata
    lines.append("# Intelligent RBAC Policy Auditor — Audit Report")
    lines.append("")
    lines.append(f"**Audit ID:** `{audit.id}`")
    lines.append(f"**Dataset ID:** `{audit.dataset_id}`")
    lines.append("**Status:** Completed")
    lines.append(
        f"**Created at:** {audit.created_at.strftime('%Y-%m-%d %H:%M:%S UTC') if audit.created_at else 'N/A'}"
    )
    lines.append(
        f"**Completed at:** {audit.completed_at.strftime('%Y-%m-%d %H:%M:%S UTC') if audit.completed_at else 'N/A'}"
    )

    if audit.parameters:
        lines.append("")
        lines.append("**Parameters:**")
        for key, value in audit.parameters.items():
            lines.append(f"- {key}: {value}")
    lines.append("")

    # Executive summary
    lines.append("---")
    lines.append("## Executive Summary")
    lines.append("")

    if audit.summary:
        summary = audit.summary
        total_users = summary.get("total_users_analysed", "N/A")
        total_findings = summary.get("total_findings", 0)
        findings_by_category = summary.get("findings_by_category", {})
        findings_by_severity = summary.get("findings_by_severity", {})

        lines.append(f"- **Total users analysed:** {total_users}")
        lines.append(f"- **Total findings:** {total_findings}")
        lines.append("")
        if findings_by_category:
            lines.append("**Findings by category:**")
            for cat, count in findings_by_category.items():
                lines.append(f"  - {cat}: {count}")
        lines.append("")
        if findings_by_severity:
            lines.append("**Findings by severity:**")
            for sev, count in findings_by_severity.items():
                lines.append(f"  - {sev}: {count}")
    else:
        lines.append("No summary available.")

    lines.append("")
    lines.append("---")
    lines.append("")

    # Group findings by severity (order: critical, high, medium, low)
    severity_order = ["critical", "high", "medium", "low"]
    grouped: dict[str, list[Finding]] = {sev: [] for sev in severity_order}
    for f in findings:
        sev = f.severity.lower()
        if sev in grouped:
            grouped[sev].append(f)
        else:
            # If LLM returned an unknown severity, put in low
            grouped["low"].append(f)

    severity_emoji = {
        "critical": "🔴",
        "high": "🟠",
        "medium": "🟡",
        "low": "⚪",
    }

    for sev in severity_order:
        sev_findings = grouped[sev]
        if not sev_findings:
            continue
        emoji = severity_emoji.get(sev, "")
        lines.append(f"## {emoji} {sev.capitalize()} Severity Findings ({len(sev_findings)})")
        lines.append("")

        for idx, finding in enumerate(sev_findings, start=1):
            lines.append(f"### {idx}. {finding.principal_name} (`{finding.principal_id}`)")
            lines.append("")
            lines.append(f"- **Category:** {finding.category}")
            lines.append(f"- **Principal type:** {finding.principal_type}")
            lines.append(
                f"- **Roles:** {', '.join(ra.get('role_name', '?') for ra in finding.role_assignments)}"
            )
            lines.append("- **Evidence:**")
            for key, value in finding.evidence.items():
                lines.append(f"  - {key}: {value}")
            lines.append(f"- **Remediation:** {finding.remediation}")
            lines.append("")
            lines.append("**Narrative:**")
            lines.append("")
            lines.append(finding.narrative)
            lines.append("")
            lines.append("---")
            lines.append("")

    # Footer
    lines.append("*Report generated by Intelligent RBAC Policy Auditor*")
    lines.append("")

    return "\n".join(lines)


def _generate_empty_report(audit: Audit) -> str:
    """Generate a minimal report when no findings were produced."""
    lines: list[str] = []
    lines.append("# Intelligent RBAC Policy Auditor — Audit Report")
    lines.append("")
    lines.append(f"**Audit ID:** `{audit.id}`")
    lines.append(f"**Dataset ID:** `{audit.dataset_id}`")
    lines.append("**Status:** Completed (no findings)")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    if audit.summary:
        lines.append(
            f"- **Total users analysed:** {audit.summary.get('total_users_analysed', 'N/A')}"
        )
        lines.append("- **Total findings:** 0")
    else:
        lines.append(
            "No findings were produced by the audit. All accounts appear to be correctly provisioned."
        )
    lines.append("")
    lines.append("*Report generated by Intelligent RBAC Policy Auditor*")
    lines.append("")
    return "\n".join(lines)
