from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.llm.base import BaseLLMProvider
from app.models.audit import Audit
from app.models.dataset import Dataset
from app.models.finding import Finding
from app.schemas.finding import FindingSchema
from app.services.preprocessor import preprocess_dataset

logger = logging.getLogger(__name__)


def run_audit(
    dataset_id: uuid.UUID,
    provider: BaseLLMProvider,
    db: Session,
    dormant_threshold_days: int = 30,
    audit_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Execute the full audit pipeline for a given dataset.

    Parameters
    ----------
    dataset_id:
        The ID of the dataset to audit.  Must exist in the ``datasets`` table.
    provider:
        An initialised LLM provider that implements ``analyze_findings``.
    db:
        Active SQLAlchemy session.  The caller is responsible for committing
        after this function returns.
    dormant_threshold_days:
        Number of days without sign-in to consider a principal dormant.

    Returns
    -------
    uuid.UUID
        The ID of the created ``Audit`` record.

    Raises
    ------
    ValueError
        If the dataset is not found, or if pre-processing fails catastrophically.
    """
    # ------------------------------------------------------------------
    # 1. Load the dataset
    # ------------------------------------------------------------------
    dataset: Dataset | None = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if dataset is None:
        raise ValueError(f"Dataset {dataset_id} not found.")

    raw_data: dict[str, Any] = dataset.raw_data
    if not raw_data:
        raise ValueError(f"Dataset {dataset_id} has no raw data.")

    logger.info(
        "Pipeline: starting audit for dataset %s (name=%r, users=%s)",
        dataset_id,
        dataset.name,
        dataset.user_count,
    )

    # ------------------------------------------------------------------
    # 2. Use the pre-created Audit record (if supplied) or create one
    # ------------------------------------------------------------------
    if audit_id is not None:
        audit: Audit | None = db.query(Audit).filter(Audit.id == audit_id).first()
        if audit is None:
            raise ValueError(f"Audit {audit_id} not found.")
        audit.status = "running"
        audit.started_at = datetime.now(UTC)
        audit.parameters = {
            "dormant_threshold_days": dormant_threshold_days,
            "llm_provider": type(provider).__name__,
        }
        db.flush()
    else:
        audit = Audit(
            dataset_id=dataset_id,
            status="running",
            parameters={
                "dormant_threshold_days": dormant_threshold_days,
                "llm_provider": type(provider).__name__,
            },
            started_at=datetime.now(UTC),
        )
        db.add(audit)
        db.flush()

    audit_id = audit.id

    try:
        # ------------------------------------------------------------------
        # 3. Run pre-processing
        # ------------------------------------------------------------------
        preprocessed = preprocess_dataset(raw_data)
        logger.info(
            "Pipeline: pre-processing complete — %d principals analysed.",
            len(preprocessed),
        )

        # ------------------------------------------------------------------
        # 4. Call the LLM provider
        # ------------------------------------------------------------------
        findings_list: list[FindingSchema] = provider.analyze_findings(preprocessed)
        logger.info(
            "Pipeline: LLM analysis returned %d findings.",
            len(findings_list),
        )

        # ------------------------------------------------------------------
        # 5. Persist findings
        # ------------------------------------------------------------------
        finding_orm_list: list[Finding] = []
        for fs in findings_list:
            finding = Finding(
                id=fs.id,
                audit_id=audit_id,
                category=fs.category,
                severity=fs.severity,
                principal_id=fs.principal_id,
                principal_name=fs.principal_name,
                principal_type=fs.principal_type,
                role_assignments=fs.role_assignments,
                evidence=fs.evidence,
                remediation=fs.remediation,
                narrative=fs.narrative,
                created_at=fs.created_at,
            )
            finding_orm_list.append(finding)
            db.add(finding)

        db.flush()

        # ------------------------------------------------------------------
        # 6. Build summary and mark audit as completed
        # ------------------------------------------------------------------
        category_counts: dict[str, int] = {}
        severity_counts: dict[str, int] = {}
        for fs in findings_list:
            cat = fs.category
            sev = fs.severity
            category_counts[cat] = category_counts.get(cat, 0) + 1
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        summary = {
            "total_users_analysed": len(preprocessed),
            "total_findings": len(findings_list),
            "findings_by_category": category_counts,
            "findings_by_severity": severity_counts,
        }

        audit.status = "completed"
        audit.completed_at = datetime.now(UTC)
        audit.summary = summary

        logger.info(
            "Pipeline: audit %s completed with %d findings.",
            audit_id,
            len(findings_list),
        )

    except Exception:
        logger.exception("Pipeline: audit %s failed.", audit_id)
        audit.status = "failed"
        audit.completed_at = datetime.now(UTC)
        # Re-raise so the caller (API endpoint) knows the audit failed.
        raise

    return audit_id
