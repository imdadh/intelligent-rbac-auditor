"""Shared response envelope schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class Meta(BaseModel):
    """Optional metadata attached to success responses."""

    total: int | None = None


class DataResponse(BaseModel):
    """Standard success envelope: {"data": ..., "meta": {...}}."""

    data: Any
    meta: Meta = Meta()


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    """Standard error envelope: {"error": {"code": ..., "message": ...}}."""

    error: ErrorDetail


class SuccessResponse(BaseModel):
    """Generic success envelope for mutation endpoints."""
    message: str = "ok"
    data: dict | None = None
    meta: Meta | dict | None = None
