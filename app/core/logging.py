"""Structured JSON logging configuration for the RBAC Policy Auditor.

This module configures structlog to emit newline-delimited JSON records to
stdout.  Every log record includes at minimum:

    timestamp      — ISO-8601 UTC timestamp
    level          — normalised log level string (info, warning, error, …)
    logger         — name of the logger that emitted the record
    correlation_id — UUID of the in-flight HTTP request (empty string when
                     called outside a request context)

Call ``configure_logging()`` once at application startup (i.e. in
``app/main.py``) before the first request is processed.  Afterwards obtain
a bound logger anywhere in the codebase with::

    from app.core.logging import get_logger
    logger = get_logger(__name__)
    logger.info("dataset_ingested", dataset_id=str(dataset.id))

Correlation IDs are propagated via a ``contextvars.ContextVar`` so that
async handlers work correctly without any thread-local gotchas.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

# ---------------------------------------------------------------------------
# Correlation ID context variable
# ---------------------------------------------------------------------------

#: Holds the correlation ID for the current request / task context.
#: Middleware sets this at the start of each request; it is read by the
#: ``_inject_correlation_id`` processor below.
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


# ---------------------------------------------------------------------------
# Custom structlog processors
# ---------------------------------------------------------------------------


def _inject_correlation_id(
    logger: Any,
    method: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Inject the current correlation ID into every log record.

    The value is read from the ``ContextVar`` so it is automatically
    scoped to the current async task / thread without any explicit
    passing.
    """
    event_dict["correlation_id"] = correlation_id_var.get()
    return event_dict


def _reorder_keys(
    logger: Any,
    method: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Reorder keys so that the canonical fields appear first in the JSON.

    Most JSON log shippers are key-order-agnostic, but consistent ordering
    makes grepping and visual inspection considerably easier.
    """
    priority_keys = ["timestamp", "level", "logger", "correlation_id", "event"]
    reordered: dict[str, Any] = {}
    for key in priority_keys:
        if key in event_dict:
            reordered[key] = event_dict.pop(key)
    reordered.update(event_dict)
    return reordered


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structlog and the stdlib ``logging`` root logger.

    This function is idempotent — calling it multiple times (e.g. during
    tests) will simply overwrite the previous configuration without side
    effects.

    Parameters
    ----------
    log_level:
        A valid Python logging level string (``DEBUG``, ``INFO``,
        ``WARNING``, ``ERROR``, ``CRITICAL``).  Case-insensitive.
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Configure the stdlib root logger so that third-party libraries that use
    # the stdlib logging module (SQLAlchemy, uvicorn, etc.) are also captured
    # and rendered through structlog's JSON formatter.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
        force=True,
    )

    # Suppress overly chatty loggers that would otherwise flood the output
    # in a development environment.
    for noisy_logger in ("uvicorn.access",):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    shared_processors: list[structlog.types.Processor] = [
        # Add log level as a string field before any other processing.
        structlog.stdlib.add_log_level,
        # Add logger name derived from the bound logger's name.
        structlog.stdlib.add_logger_name,
        # Inject the request-scoped correlation ID.
        _inject_correlation_id,
        # Render exception info into the event dict if present.
        structlog.processors.ExceptionRenderer(),
        # Render the ISO-8601 UTC timestamp.
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
        # Normalise positional arguments surfaced via stdlib log calls into
        # the event dict.
        structlog.stdlib.PositionalArgumentsFormatter(),
        # Stack info renderer (adds stack_info key when log includes stack).
        structlog.processors.StackInfoRenderer(),
        # Reorder keys for readability.
        _reorder_keys,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            # Render the final event dict as a JSON string.
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog bound logger with the given name.

    Usage::

        logger = get_logger(__name__)
        logger.info("pipeline_started", audit_id=str(audit_id))

    The returned logger is a lightweight wrapper — it does not allocate any
    resources until the first log call, and it is safe to call at module
    import time.

    Parameters
    ----------
    name:
        Typically ``__name__`` of the calling module.  This value appears
        as the ``logger`` field in every JSON record emitted by this logger.
    """
    return structlog.get_logger(name)
