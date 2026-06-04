from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.audit import Audit
from app.models.dataset import Dataset
from app.schemas.audit import AuditCreate, AuditStatusResponse
from app.schemas.common import DataResponse, Meta
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
def _run_audit_background(dataset_id: uuid.UUID, dormant_threshold_days: int) -> None:
    """Execute the audit pipeline in background and update the audit record.

    This function opens and closes its own database session to avoid
    sharing the request's session.
    """
    db: Session = _get_background_db()
    try:
        # Instantiate the LLM provider based on configuration
        settings = get_settings()
        if settings.llm_provider == "azure_openai":
            from app.llm.azure_provider import AzureOpenAIProvider

            provider = AzureOpenAIProvider()
        else:
            from app.llm.openai_provider import OpenAIProvider

            provider = OpenAIProvider()

        run_audit(
            dataset_id=dataset_id,
            provider=provider,
            db=db,
            dormant_threshold_days=dormant_threshold_days,
        )
        db.commit()
        logger.info("Background audit %s completed successfully.", dataset_id)
    except Exception:
        logger.exception("Background audit %s failed.", dataset_id)
        db.rollback()
        # Update the audit status to 'failed' if the pipeline raised
        try:
            audit: Audit | None = (
                db.query(Audit).filter(Audit.dataset_id == dataset_id).first()
            )
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
    dataset: Dataset | None = (
        db.query(Dataset).filter(Dataset.id == payload.dataset_id).first()
    )
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset {payload.dataset_id} not found.",
        )

    settings = get_settings()
    dormant_threshold_days = settings.dormant_threshold_days

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

    # Schedule the background task
    background_tasks.add_task(
        _run_audit_background,
        dataset_id=payload.dataset_id,
        dormant_threshold_days=dormant_threshold_days,
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


# Re-usable dependency for database session
def get_db() -> Session:
    """FastAPI dependency that yields a database session."""
    from app.models.base import SessionLocal, _ensure_session_factory_bound

    _ensure_session_factory_bound()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
