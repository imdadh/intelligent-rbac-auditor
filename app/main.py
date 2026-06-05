"""FastAPI application factory and lifespan events."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.models.base import check_database_connectivity

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    configure_logging(settings.log_level)

    app = FastAPI(
        title="Intelligent RBAC Policy Auditor",
        description=(
            "Production-grade service that audits Azure AD RBAC role assignments "
            "using structured LLM analysis."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    @app.get("/health", tags=["health"])
    async def health() -> dict:  # type: ignore[type-arg]
        db_ok = check_database_connectivity()
        return {"status": "ok", "database": "connected" if db_ok else "unavailable"}

    app.include_router(api_router)

    static_path = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

    @app.get("/")
    async def root() -> FileResponse:
        return FileResponse(static_path / "index.html")

    from app.core.middleware import CorrelationIDMiddleware
    app.add_middleware(CorrelationIDMiddleware)

    logger.info("FastAPI application created (log_level=%s)", settings.log_level)

    return app


app = create_app()
