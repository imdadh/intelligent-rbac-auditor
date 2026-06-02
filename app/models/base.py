"""SQLAlchemy declarative base, engine, and session factory.

This module is the single source of truth for database connectivity.
All ORM models inherit from ``Base``; the engine and session factory
exported here are used throughout the application and by Alembic's
migration environment.

Design decisions
----------------
* **Synchronous engine** — Phase 1 uses a standard synchronous
  ``Engine`` backed by ``psycopg2``.  The FastAPI route handlers that
  touch the database run their blocking calls inside
  ``asyncio.get_event_loop().run_in_executor`` or, more commonly, accept
  the slight latency in exchange for dramatically simpler session
  lifecycle management.  Switching to an async engine (``asyncpg`` +
  ``create_async_engine``) is a contained refactor when the need arises.

* **Scoped factory** — ``SessionLocal`` is a plain ``sessionmaker``
  instance.  Callers are responsible for the session lifecycle::

      with SessionLocal() as session:
          session.add(obj)
          session.commit()

  FastAPI route dependencies that need a session should use the
  ``get_db`` context manager exported below.

* **Engine is created lazily** — ``_engine`` is built the first time
  ``get_engine()`` is called rather than at import time.  This keeps
  module import fast and allows tests to patch ``DATABASE_URL`` before
  the engine is constructed.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """Project-wide SQLAlchemy declarative base class.

    All ORM models must inherit from this class.  The ``metadata``
    attribute is passed to Alembic's ``migrations/env.py`` so that schema
    changes are detected automatically via ``--autogenerate``.
    """


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

# Module-level cache for the engine singleton.  Initialised on first call
# to ``get_engine()``.
_engine: Engine | None = None


def get_engine() -> Engine:
    """Return the application-wide SQLAlchemy engine, creating it on first call.

    The engine is configured for a standard PostgreSQL connection using the
    ``DATABASE_URL`` environment variable (via ``Settings``).  Connection
    pooling uses SQLAlchemy's built-in ``QueuePool`` with defaults that are
    appropriate for a single-process FastAPI deployment.

    The ``asyncpg`` URL scheme is normalised to the ``psycopg2``-compatible
    ``postgresql://`` prefix so that this synchronous engine works regardless
    of how ``DATABASE_URL`` was originally set (e.g. by ``docker-compose.yml``
    which always uses the plain scheme).

    Returns
    -------
    Engine
        A configured SQLAlchemy engine instance.
    """
    global _engine

    if _engine is None:
        settings = get_settings()
        url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        _engine = create_engine(
            url,
            # Echo SQL statements at DEBUG level — controlled by the pool
            # pre-ping setting below rather than `echo=True` to avoid
            # flooding production logs.
            echo=False,
            # Verify connections retrieved from the pool are still alive.
            # This transparently handles transient TCP disconnections without
            # surfacing errors to the application layer.
            pool_pre_ping=True,
            # Sensible pool sizing for a single-process service.  Increase
            # ``pool_size`` and ``max_overflow`` when horizontal scaling is
            # added.
            pool_size=5,
            max_overflow=10,
        )

    return _engine


def reset_engine() -> None:
    """Dispose the cached engine and reset the module-level singleton.

    Intended for use in tests that need to point the engine at a different
    database URL between test cases.  Call ``get_settings.cache_clear()``
    before this function to ensure the new URL is picked up.

    .. warning::
        This function must **not** be called in production code paths.
        Disposing the engine mid-flight drops all pooled connections.
    """
    global _engine

    if _engine is not None:
        _engine.dispose()
        _engine = None


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

#: Application-wide session factory.  Import and call this directly when a
#: context manager is not sufficient (e.g., background tasks that span
#: multiple functions).
#:
#: Prefer the ``get_db`` dependency in FastAPI route handlers.
SessionLocal: sessionmaker[Session] = sessionmaker(
    # The engine is bound lazily so that the factory can be imported at
    # module level without triggering a database connection.
    bind=None,
    autocommit=False,
    autoflush=False,
    class_=Session,
)


def _ensure_session_factory_bound() -> None:
    """Bind ``SessionLocal`` to the engine if not already done.

    ``sessionmaker`` supports late binding via ``configure()``.  We defer
    binding until the first session is requested so that tests can patch the
    settings before the engine is created.
    """
    if SessionLocal.kw.get("bind") is None:  # type: ignore[union-attr]
        SessionLocal.configure(bind=get_engine())


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def get_db() -> Generator[Session, Any, None]:
    """Yield a database session and guarantee it is closed after the request.

    Intended for use as a FastAPI dependency::

        from fastapi import Depends
        from app.models.base import get_db

        @router.get("/items/{item_id}")
        def read_item(item_id: str, db: Session = Depends(get_db)):
            return db.get(Item, item_id)

    The session is committed automatically on clean exit and rolled back if
    an exception propagates out of the route handler.

    Yields
    ------
    Session
        An active SQLAlchemy ``Session`` bound to the configured database.
    """
    _ensure_session_factory_bound()
    db: Session = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Health-check helper
# ---------------------------------------------------------------------------


def check_database_connectivity() -> bool:
    """Return ``True`` if a trivial query against the database succeeds.

    Used by the ``GET /health`` endpoint to verify that the connection pool
    can reach PostgreSQL.  Catches all exceptions so the caller always
    receives a boolean rather than a stack trace.

    Returns
    -------
    bool
        ``True`` when the database is reachable; ``False`` otherwise.
    """
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
