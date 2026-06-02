"""Pydantic schemas for dataset ingestion and retrieval."""
from __future__ import annotations
import uuid
from datetime import datetime
from pydantic import BaseModel, Field


class DatasetCreate(BaseModel):
    """Payload for POST /api/v1/datasets."""
    name: str = Field(min_length=1, max_length=255)
    data: dict = Field(description="Raw Azure AD snapshot JSON.")


class DatasetResponse(BaseModel):
    """Response body after successful dataset ingestion."""
    id: uuid.UUID
    name: str
    user_count: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
