"""Pydantic schema for individual audit findings (FR-13)."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel


class FindingSchema(BaseModel):
    """One finding as returned by the audit pipeline."""
    id: uuid.UUID
    audit_id: uuid.UUID
    category: str
    severity: str
    principal_id: str
    principal_name: str
    principal_type: str
    role_assignments: list[Any]
    evidence: dict[str, Any]
    remediation: str
    narrative: str
    created_at: datetime

    model_config = {"from_attributes": True}
