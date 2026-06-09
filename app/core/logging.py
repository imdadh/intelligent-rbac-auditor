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

    All loggers — whether obtained via ``structlog.get_logger`` or the
    standard ``logging.getLogger`` — will produce newline-delimited JSON
    records to stdout.  Every record includes the current request's
    correlation ID (empty string when no request context is active).

    Parameters
    ----------
    log_level:
        A valid Python logging level string (``DEBUG``, ``INFO``,
        ``WARNING``, ``ERROR``, ``CRITICAL``).  Case-insensitive.
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # ------------------------------------------------------------------
    # Remove any existing handlers on the root logger to avoid duplicates
    # when configure_logging is called more than once (e.g. in tests).
    # ------------------------------------------------------------------
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # ------------------------------------------------------------------
    # Build the shared processor chain for both stdlib and structlog
    # loggers.
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Configure a logging handler that feeds stdlib log records through
    # the structlog processor chain and outputs JSON.
    # ------------------------------------------------------------------
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setLevel(numeric_level)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=shared_processors
            + [
                # Render the final event dict as a JSON string.
                structlog.processors.JSONRenderer(),
            ],
            foreign_pre_chain=[
                # For log records that come from third-party libraries using
                # plain stdlib formatting, extract the message and inject
                # standard fields so the JSON output is consistent.
                structlog.stdlib.ExtraAdder(),
                _inject_correlation_id,
                structlog.stdlib.add_log_level,
                structlog.stdlib.add_logger_name,
            ],
        )
    )

    root_logger.addHandler(handler)
    root_logger.setLevel(numeric_level)

    # ------------------------------------------------------------------
    # Suppress overly chatty loggers that would otherwise flood the output
    # in a development environment.
    # ------------------------------------------------------------------
    for noisy_logger in ("uvicorn.access",):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    # ------------------------------------------------------------------
    # Configure structlog itself so that structlog.get_logger returns a
    # bound logger that delegates to the stdlib logging system.  This
    # ensures that structlog loggers also go through the ProcessorFormatter
    # configured above.
    # ------------------------------------------------------------------
    structlog.configure(
        processors=shared_processors
        + [
            # Render the final event dict as a JSON string.
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
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
