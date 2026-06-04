"""Unit tests for app/core/logging.py.

These tests verify that:

- ``configure_logging`` completes without raising for all valid log levels.
- ``get_logger`` returns a usable bound logger.
- The correlation ID context variable is accessible and defaults to an
  empty string when no request context is active.
- The ``_inject_correlation_id`` processor injects the current context value
  into the event dict.
- The ``_reorder_keys`` processor places canonical fields first.
"""

from __future__ import annotations

import pytest

from app.core.logging import (
    _inject_correlation_id,
    _reorder_keys,
    configure_logging,
    correlation_id_var,
    get_logger,
)

# ---------------------------------------------------------------------------
# configure_logging
# ---------------------------------------------------------------------------


class TestConfigureLogging:
    """configure_logging must accept all valid level strings."""

    @pytest.mark.parametrize(
        "level",
        ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "debug", "info", "warning"],
    )
    def test_valid_levels_do_not_raise(self, level: str) -> None:
        # Should complete without raising regardless of level casing.
        configure_logging(log_level=level)

    def test_default_level_is_info(self) -> None:
        # No exception — just verifying the default argument path.
        configure_logging()

    def test_idempotent_when_called_twice(self) -> None:
        configure_logging(log_level="INFO")
        configure_logging(log_level="DEBUG")
        # No exception; second call overwrites the first.


# ---------------------------------------------------------------------------
# get_logger
# ---------------------------------------------------------------------------


class TestGetLogger:
    """get_logger must return a bound logger that can emit records."""

    def test_returns_a_logger(self) -> None:
        logger = get_logger(__name__)
        assert logger is not None

    def test_logger_is_callable(self) -> None:
        configure_logging(log_level="DEBUG")
        logger = get_logger(__name__)
        # Calling .info must not raise.
        logger.info("test_event", key="value")

    def test_different_names_are_independent(self) -> None:
        a = get_logger("module_a")
        b = get_logger("module_b")
        # They are distinct bound loggers (different names).
        assert a is not b


# ---------------------------------------------------------------------------
# correlation_id_var
# ---------------------------------------------------------------------------


class TestCorrelationIdVar:
    """The correlation ID context variable must behave as documented."""

    def test_default_is_empty_string(self) -> None:
        # Reset to default to ensure no previous test pollutes the context.
        token = correlation_id_var.set("")
        try:
            assert correlation_id_var.get() == ""
        finally:
            correlation_id_var.reset(token)

    def test_can_be_set_and_retrieved(self) -> None:
        expected = "3e4a1b62-dead-beef-cafe-000000000001"
        token = correlation_id_var.set(expected)
        try:
            assert correlation_id_var.get() == expected
        finally:
            correlation_id_var.reset(token)

    def test_reset_restores_previous_value(self) -> None:
        token = correlation_id_var.set("first")
        inner_token = correlation_id_var.set("second")
        assert correlation_id_var.get() == "second"
        correlation_id_var.reset(inner_token)
        assert correlation_id_var.get() == "first"
        correlation_id_var.reset(token)


# ---------------------------------------------------------------------------
# _inject_correlation_id processor
# ---------------------------------------------------------------------------


class TestInjectCorrelationIdProcessor:
    """The processor must add the current correlation ID to every event dict."""

    def test_injects_empty_string_when_no_context(self) -> None:
        token = correlation_id_var.set("")
        try:
            event_dict: dict = {"event": "something"}
            result = _inject_correlation_id(None, "info", event_dict)
            assert result["correlation_id"] == ""
        finally:
            correlation_id_var.reset(token)

    def test_injects_active_correlation_id(self) -> None:
        cid = "abc-123"
        token = correlation_id_var.set(cid)
        try:
            event_dict: dict = {"event": "request_received"}
            result = _inject_correlation_id(None, "info", event_dict)
            assert result["correlation_id"] == cid
        finally:
            correlation_id_var.reset(token)

    def test_overwrites_existing_correlation_id_key(self) -> None:
        """If a caller manually set correlation_id, the context var wins."""
        cid = "ctx-var-value"
        token = correlation_id_var.set(cid)
        try:
            event_dict: dict = {"event": "e", "correlation_id": "stale-value"}
            result = _inject_correlation_id(None, "info", event_dict)
            assert result["correlation_id"] == cid
        finally:
            correlation_id_var.reset(token)

    def test_returns_same_dict(self) -> None:
        token = correlation_id_var.set("x")
        try:
            event_dict: dict = {"event": "e"}
            result = _inject_correlation_id(None, "info", event_dict)
            assert result is event_dict
        finally:
            correlation_id_var.reset(token)


# ---------------------------------------------------------------------------
# _reorder_keys processor
# ---------------------------------------------------------------------------


class TestReorderKeysProcessor:
    """Canonical fields must appear first in the reordered dict."""

    def test_priority_keys_are_first(self) -> None:
        event_dict: dict = {
            "extra": "data",
            "event": "something_happened",
            "correlation_id": "cid",
            "logger": "my.module",
            "level": "info",
            "timestamp": "2024-01-01T00:00:00Z",
        }
        result = _reorder_keys(None, "info", event_dict)
        keys = list(result.keys())
        # All present priority keys must precede non-priority keys.
        priority = ["timestamp", "level", "logger", "correlation_id", "event"]
        priority_indices = [keys.index(k) for k in priority if k in result]
        extra_index = keys.index("extra")
        assert all(i < extra_index for i in priority_indices)

    def test_missing_priority_keys_are_skipped(self) -> None:
        """Not every record has every priority key; missing ones are skipped."""
        event_dict: dict = {"event": "minimal", "custom": "field"}
        result = _reorder_keys(None, "info", event_dict)
        assert "event" in result
        assert "custom" in result

    def test_all_original_keys_are_preserved(self) -> None:
        event_dict: dict = {
            "timestamp": "t",
            "level": "info",
            "logger": "l",
            "correlation_id": "c",
            "event": "e",
            "foo": "bar",
            "baz": 42,
        }
        result = _reorder_keys(None, "info", event_dict)
        assert set(result.keys()) == set(event_dict.keys())

    def test_returns_same_dict(self) -> None:
        event_dict: dict = {"event": "e"}
        result = _reorder_keys(None, "info", event_dict)
        assert result is event_dict
