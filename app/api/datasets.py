from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.models.base import get_db
from app.models.dataset import Dataset
from app.schemas.common import DataResponse, Meta
from app.schemas.dataset_schema import AzureADDatasetPayload
from app.services.ingestion import DatasetIngestionError, ingest_dataset

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/datasets", tags=["datasets"])

# ------------------------------------------------------------------
# Path to the bundled sample dataset (relative to the project root)
# ------------------------------------------------------------------
_SAMPLE_DATASET_PATH: Path | None = None


def _get_sample_dataset_path() -> Path:
    """Return resolved path to ``data/sample_dataset.json``.

    The path is computed relative to the location of this file
    (``app/api/datasets.py``) by walking up to the project root.
    """
    global _SAMPLE_DATASET_PATH
    if _SAMPLE_DATASET_PATH is None:
        # This file lives at app/api/datasets.py, so the project root is
        # (this file's parent) / .. / ..
        current_dir = Path(__file__).resolve().parent  # app/api
        project_root = current_dir.parent.parent  # project root
        _SAMPLE_DATASET_PATH = project_root / "data" / "sample_dataset.json"
    return _SAMPLE_DATASET_PATH


# ------------------------------------------------------------------
# POST /api/v1/datasets/sample  —  load the pre‑generated sample dataset
# ------------------------------------------------------------------


@router.post(
    "/sample",
    response_model=DataResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Load the bundled sample dataset",
    description=(
        "Ingests the pre‑generated synthetic Azure AD snapshot from "
        "``data/sample_dataset.json`` and returns the created dataset's "
        "metadata.  This is the recommended way to quickly bootstrap the "
        "demo."
    ),
    responses={
        500: {"description": "Sample dataset file not found or unreadable"},
        422: {"description": "Sample dataset failed schema validation"},
    },
)
def load_sample_dataset(
    db: Session = Depends(get_db),
) -> DataResponse:
    """Read the sample dataset from disk, validate it, and persist it."""
    sample_path = _get_sample_dataset_path()

    if not sample_path.exists():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"Sample dataset file not found at {sample_path}. "
                "Ensure the file exists or run `make sample-data`."
            ),
        )

    try:
        with sample_path.open("r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read or parse sample dataset: {exc}",
        )

    try:
        dataset = ingest_dataset(
            name="Sample Dataset (pre-generated)",
            data=raw_data,
            db=db,
        )
        db.commit()
    except DatasetIngestionError as exc:
        logger.warning("Sample dataset ingestion failed: %s", exc.message)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.message,
        )

    logger.info(
        "Sample dataset loaded: %s (%d users)",
        dataset.id,
        dataset.user_count,
    )

    return DataResponse(
        data={
            "id": str(dataset.id),
            "name": dataset.name,
            "user_count": dataset.user_count,
            "created_at": (dataset.created_at.isoformat() if dataset.created_at else None),
        },
        meta=Meta(),
    )


# ------------------------------------------------------------------
# Existing endpoints (unchanged)
# ------------------------------------------------------------------


@router.post(
    "",
    response_model=DataResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        422: {"description": "Validation error"},
    },
)
def create_dataset(
    payload: AzureADDatasetPayload,
    db: Session = Depends(get_db),
) -> DataResponse:
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

    return DataResponse(
        data={
            "id": str(dataset.id),
            "name": dataset.name,
            "user_count": dataset.user_count,
            "created_at": (dataset.created_at.isoformat() if dataset.created_at else None),
        },
        meta=Meta(total=dataset.user_count),
    )


@router.get(
    "/{dataset_id}",
    response_model=DataResponse,
    responses={
        404: {"description": "Dataset not found"},
    },
)
def get_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
) -> DataResponse:
    """Retrieve a previously ingested dataset's metadata by ID."""
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if dataset is None:
        raise HTTPException(
            status_code=404,
            detail=f"Dataset with id '{dataset_id}' not found.",
        )

    return DataResponse(
        data={
            "id": str(dataset.id),
            "name": dataset.name,
            "user_count": dataset.user_count,
            "created_at": (dataset.created_at.isoformat() if dataset.created_at else None),
        },
        meta=Meta(total=dataset.user_count),
    )
