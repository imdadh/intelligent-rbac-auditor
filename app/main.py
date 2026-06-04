from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.middleware import CorrelationIDMiddleware, setup_middleware

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Application factory for the Intelligent RBAC Policy Auditor.

    Creates a FastAPI instance, configures middleware, logging, and
    registers all API routes under the ``/api/v1`` prefix.
    """
    settings = get_settings()

    configure_logging(settings.log_level)

    app = FastAPI(
        title="Intelligent RBAC Policy Auditor",
        description=(
            "A production-grade service that audits Azure AD RBAC role "
            "assignments using structured LLM analysis."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url=None,
    )

    # ---------- Middleware ----------
    setup_middleware(app, settings)
    app.add_middleware(CorrelationIDMiddleware)

    # ---------- Routers ----------
    app.include_router(api_router)

    # ---------- Static files (web UI) ----------
    app.mount("/static", StaticFiles(directory="app/static", html=True), name="static")

    # ---------- Lifespan events ----------
    @app.on_event("startup")
    async def on_startup() -> None:
        logger.info("Application started")

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        logger.info("Application shutting down")

    return app


app = create_app()
