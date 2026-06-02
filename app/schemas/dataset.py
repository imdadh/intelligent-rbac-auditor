"""Pydantic schemas for dataset ingestion and retrieval."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field, field_validator


class SignInActivity(BaseModel):
    lastSignIn: str | None = None


class RoleAssignment(BaseModel):
    roleId: str
    roleName: str
    assignmentType: str
    assignedAt: str | None = None


class UserEntry(BaseModel):
    identifier: str
    displayName: str
    roleAssignments: list[RoleAssignment]
    signInActivity: SignInActivity


class DatasetCreate(BaseModel):
    """Payload for POST /api/v1/datasets."""
    name: str = Field(min_length=1, max_length=255)
    data: dict[str, Any] = Field(description="Raw Azure AD snapshot JSON.")

    @field_validator("data")
    @classmethod
    def validate_data_schema(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Validate the uploaded dataset has required fields per FR-2."""
        if "users" not in v:
            raise ValueError("Dataset must contain a top-level 'users' array.")
        users = v["users"]
        if not isinstance(users, list):
            raise ValueError("'users' must be an array.")
        for i, user in enumerate(users):
            missing = [f for f in ("identifier", "displayName", "roleAssignments", "signInActivity")
                       if f not in user]
            if missing:
                raise ValueError(
                    f"User at index {i} is missing required fields: {missing}"
                )
            for j, ra in enumerate(user.get("roleAssignments", [])):
                ra_missing = [f for f in ("roleId", "roleName", "assignmentType") if f not in ra]
                if ra_missing:
                    raise ValueError(
                        f"roleAssignment at users[{i}].roleAssignments[{j}] "
                        f"is missing: {ra_missing}"
                    )
        return v


class DatasetResponse(BaseModel):
    """Response body after successful dataset ingestion."""
    id: uuid.UUID
    name: str
    user_count: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
