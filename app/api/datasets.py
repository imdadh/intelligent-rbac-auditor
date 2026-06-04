from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.models.base import get_db
from app.models.dataset import Dataset
from app.schemas.common import ErrorResponse, SuccessResponse
from app.schemas.dataset_schema import AzureADDatasetPayload
from app.services.ingestion import DatasetIngestionError, ingest_dataset

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/datasets", tags=["datasets"])


@router.post(
    "",
    response_model=SuccessResponse,
    status_code=201,
    responses={
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
)
def create_dataset(
    payload: AzureADDatasetPayload,
    db: Session = Depends(get_db),
) -> SuccessResponse:
    """Ingest a synthetic Azure AD role-assignment export.

    The request body must conform to the ``AzureADDatasetPayload`` schema.
    On success the dataset is persisted and its metadata returned.
    """
    try:
        dataset = ingest_dataset(
            name="API upload",
            data=payload.model_dump(mode="json"),
            db=db,
        )
        db.commit()
    except DatasetIngestionError as exc:
        logger.warning("Dataset ingestion failed: %s", exc.message)
        raise HTTPException(status_code=422, detail=exc.message)

    return SuccessResponse(
        data={
            "id": str(dataset.id),
            "name": dataset.name,
            "user_count": dataset.user_count,
            "created_at": (
                dataset.created_at.isoformat() if dataset.created_at else None
            ),
        },
        meta={"record_count": dataset.user_count},
    )


@router.get(
    "/{dataset_id}",
    response_model=SuccessResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Dataset not found"},
    },
)
def get_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
) -> SuccessResponse:
    """Retrieve a previously ingested dataset's metadata by ID."""
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if dataset is None:
        raise HTTPException(
            status_code=404,
            detail=f"Dataset with id '{dataset_id}' not found.",
        )

    return SuccessResponse(
        data={
            "id": str(dataset.id),
            "name": dataset.name,
            "user_count": dataset.user_count,
            "created_at": (
                dataset.created_at.isoformat() if dataset.created_at else None
            ),
        },
        meta={"record_count": dataset.user_count},
    )
