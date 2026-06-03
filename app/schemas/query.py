"""Pydantic schemas for natural-language query interface."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    """Payload for POST /api/v1/query."""

    dataset_id: uuid.UUID
    question: str = Field(min_length=1, max_length=2000)


class QueryResponse(BaseModel):
    """Response from the query engine."""

    question: str
    structured_data: list[Any]
    natural_language_summary: str
    answerable: bool = True
