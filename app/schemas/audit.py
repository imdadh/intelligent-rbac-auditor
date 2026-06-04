from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.finding import FindingSchema


class AuditCreate(BaseModel):
    """Request payload for triggering a new audit."""

    dataset_id: UUID = Field(..., description="The ID of the dataset to audit.")


class AuditStatusResponse(BaseModel):
    """Response schema for audit status (without full findings)."""

    id: UUID
    dataset_id: UUID
    status: str
    parameters: dict[str, Any] = {}
    summary: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class AuditDetailResponse(BaseModel):
    """Response schema for a completed audit with full findings."""

    id: UUID
    dataset_id: UUID
    status: str
    parameters: dict[str, Any] = {}
    summary: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    findings: list[FindingSchema] = Field(
        default_factory=list,
        description="Structured findings from the audit (present when status is completed).",
    )
