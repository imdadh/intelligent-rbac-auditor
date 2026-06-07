from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.llm import get_llm_provider
from app.models.base import get_db
from app.models.dataset import Dataset
from app.schemas.common import DataResponse, Meta
from app.schemas.query import QueryRequest, QueryResponse
from app.services.preprocessor import preprocess_dataset
from app.services.query_engine import QueryEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/query", tags=["query"])


@router.post(
    "",
    response_model=DataResponse,
    status_code=status.HTTP_200_OK,
    summary="Ask a natural-language question about a dataset",
    description=(
        "Accepts a dataset ID and a natural-language question, "
        "interprets the question against the loaded dataset, and returns "
        "a structured answer and a plain-language summary. "
        "If the question cannot be answered from the available data, "
        "the response will indicate that the question is unanswerable."
    ),
)
async def query_dataset(
    payload: QueryRequest,
    db: Session = Depends(get_db),
) -> DataResponse:
    """Answer a natural-language question about a previously ingested dataset.

    The endpoint pre-processes the dataset to build a context summary,
    then delegates to the configured LLM provider to interpret and answer
    the question.
    """
    logger.info(
        "Query request received: dataset_id=%s, question=%s",
        payload.dataset_id,
        payload.question[:80],
    )

    # ------------------------------------------------------------------
    # 1. Load the dataset
    # ------------------------------------------------------------------
    dataset: Dataset | None = db.query(Dataset).filter(Dataset.id == payload.dataset_id).first()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset {payload.dataset_id} not found.",
        )

    raw_data = dataset.raw_data
    if not raw_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Dataset {payload.dataset_id} contains no raw data.",
        )

    # ------------------------------------------------------------------
    # 2. Pre-process the dataset to derive features
    # ------------------------------------------------------------------
    try:
        preprocessed = preprocess_dataset(raw_data)
        logger.debug(
            "Pre-processed %d principals for query context.",
            len(preprocessed),
        )
    except Exception as exc:
        logger.exception("Pre-processing failed for dataset %s.", payload.dataset_id)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to pre-process dataset: {exc}",
        )

    # ------------------------------------------------------------------
    # 3. Build the query engine and answer the question
    # ------------------------------------------------------------------
    try:
        provider = get_llm_provider()
        engine = QueryEngine(provider)
        query_response: QueryResponse = engine.answer(
            question=payload.question,
            dataset_name=dataset.name,
            dataset_id=str(payload.dataset_id),
            preprocessed_principals=preprocessed,
        )
    except Exception as exc:
        logger.exception("LLM query failed for dataset %s.", payload.dataset_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process query: {exc}",
        )

    # ------------------------------------------------------------------
    # 4. Log the query (non-blocking; do not fail the request on log failure)
    # ------------------------------------------------------------------
    try:
        from app.models.query_log import QueryLog

        log_entry = QueryLog(
            dataset_id=payload.dataset_id,
            question=payload.question,
            answer=query_response.model_dump(mode="json"),
        )
        db.add(log_entry)
        db.commit()
    except Exception:
        logger.warning("Failed to persist query log (non-fatal).")

    logger.info(
        "Query processed: answerable=%s, dataset_id=%s",
        query_response.answerable,
        payload.dataset_id,
    )

    return DataResponse(
        data=query_response.model_dump(mode="json"),
        meta=Meta(),
    )
