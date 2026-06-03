"""Pydantic schemas for audit lifecycle."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.finding import FindingSchema


class AuditCreate(BaseModel):
    """Payload for POST /api/v1/audits."""

    dataset_id: uuid.UUID


class AuditStatusResponse(BaseModel):
    """Polling response from GET /api/v1/audits/{id}."""

    id: uuid.UUID
    dataset_id: uuid.UUID
    status: str
    parameters: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    error_message: str | None = None

    model_config = {"from_attributes": True}


class AuditResultResponse(AuditStatusResponse):
    """Full audit result including findings."""

    findings: list[FindingSchema] = []
