from __future__ import annotations

import datetime

import pytest

from app.services.preprocessor import (
    compute_days_since_last_signin,
    compute_privileged_role_count,
    compute_role_tier,
    preprocess_dataset,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(uid: str, name: str = "User") -> dict:
    return {
        "id": uid,
        "displayName": name,
        "userPrincipalName": f"{uid}@example.com",
        "userType": "Member",
        "accountEnabled": True,
    }


def _make_role_assignment(
    principal_id: str,
    role_name: str,
    role_id: str = "role-1",
    assignment_type: str = "direct",
    assigned_via: str | None = None,
    assigned_at: str | None = None,
) -> dict:
    return {
        "id": f"ra-{principal_id}-{role_id}",
        "principalId": principal_id,
        "roleDefinitionId": role_id,
        "roleName": role_name,
        "assignmentType": assignment_type,
        "assignedVia": assigned_via,
        "assignedAt": assigned_at or "2024-01-01T00:00:00Z",
    }


def _make_signin_log(
    user_id: str,
    timestamp: str,
    app_name: str = "Azure Portal",
    status: str = "Success",
) -> dict:
    return {
        "id": f"log-{user_id}-{timestamp}",
        "userId": user_id,
        "userDisplayName": "User",
        "signInTimestamp": timestamp,
        "appDisplayName": app_name,
        "status": status,
        "ipAddress": "203.0.113.42",
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def simple_dataset() -> dict:
    """A minimal dataset with one user, one direct role, one sign-in log."""
    return {
        "users": [_make_user("u1", "Alice")],
        "roleAssignments": [
            _make_role_assignment(
                "u1", "Global Administrator", assigned_at="2024-01-15T08:00:00Z"
            )
        ],
        "signInLogs": [_make_signin_log("u1", "2024-10-01T10:00:00Z")],
        "groups": [],
    }


@pytest.fixture
def dataset_with_group_and_inherited_role() -> dict:
    """A dataset where a user gets a role via group membership."""
    return {
        "users": [
            _make_user("u1", "Bob"),
            _make_user("u2", "Carol"),
        ],
        "roleAssignments": [
            _make_role_assignment(
                "u1",
                "User Administrator",
                role_id="role-useradmin",
                assignment_type="group",
                assigned_via="g1",
            ),
            _make_role_assignment(
                "u2",
                "Security Reader",
                role_id="role-secreader",
                assignment_type="direct",
            ),
        ],
        "signInLogs": [
            _make_signin_log("u1", "2024-09-20T12:00:00Z"),
            _make_signin_log("u2", "2024-08-15T08:00:00Z"),
        ],
        "groups": [
            {
                "id": "g1",
                "displayName": "IT Support",
                "isRoleAssignable": True,
                "members": ["u1"],
                "assignedRoles": ["role-useradmin"],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Tests for compute_days_since_last_signin
# ---------------------------------------------------------------------------


class TestComputeDaysSinceLastSignin:
    """Unit tests for the `compute_days_since_last_signin` function."""

    def test_with_recent_signin(self) -> None:
        """A user with a sign-in yesterday should return 1 day."""
        now = datetime.datetime(2024, 10, 2, 0, 0, 0)
        logs = [_make_signin_log("u1", "2024-10-01T10:00:00Z")]
        days = compute_days_since_last_signin("u1", logs, reference_datetime=now)
        assert days == 1

    def test_with_no_signin_logs(self) -> None:
        """A user with no sign-in logs should return None."""
        days = compute_days_since_last_signin("u1", [], reference_datetime=None)
        assert days is None

    def test_with_multiple_logs_picks_latest(self) -> None:
        """Multiple logs: should use the most recent timestamp."""
        now = datetime.datetime(2024, 10, 5, 0, 0, 0)
        logs = [
            _make_signin_log("u1", "2024-10-01T10:00:00Z"),
            _make_signin_log("u1", "2024-10-04T08:00:00Z"),
        ]
        days = compute_days_since_last_signin("u1", logs, reference_datetime=now)
        assert days == 1

    def test_default_reference_is_now(self, monkeypatch) -> None:
        """When no reference_datetime is given, use current UTC time."""

        # Hard to mock precisely, just ensure it doesn't raise.
        logs = [_make_signin_log("u1", "2024-10-01T10:00:00Z")]
        result = compute_days_since_last_signin("u1", logs)
        assert isinstance(result, int) or result is None

    def test_signin_timestamp_in_future_returns_zero(self) -> None:
        """A sign-in in the future should treat as 0 days."""
        now = datetime.datetime(2024, 10, 1, 0, 0, 0)
        logs = [_make_signin_log("u1", "2025-01-01T00:00:00Z")]
        days = compute_days_since_last_signin("u1", logs, reference_datetime=now)
        assert days == 0


# ---------------------------------------------------------------------------
# Tests for compute_role_tier
# ---------------------------------------------------------------------------


class TestComputeRoleTier:
    """Unit tests for role tier classification."""

    def test_global_administrator_is_critical(self) -> None:
        tier = compute_role_tier("Global Administrator")
        assert tier == "critical"

    def test_privileged_role_administrator_is_critical(self) -> None:
        tier = compute_role_tier("Privileged Role Administrator")
        assert tier == "critical"

    def test_exchange_administrator_is_high(self) -> None:
        tier = compute_role_tier("Exchange Administrator")
        assert tier == "high"

    def test_user_administrator_is_high(self) -> None:
        tier = compute_role_tier("User Administrator")
        assert tier == "high"

    def test_security_reader_is_medium(self) -> None:
        tier = compute_role_tier("Security Reader")
        assert tier == "medium"

    def test_reports_reader_is_low(self) -> None:
        tier = compute_role_tier("Reports Reader")
        assert tier == "low"

    def test_unknown_role_defaults_to_low(self) -> None:
        tier = compute_role_tier("Some obscure role")
        assert tier == "low"


# ---------------------------------------------------------------------------
# Tests for compute_privileged_role_count
# ---------------------------------------------------------------------------


class TestComputePrivilegedRoleCount:
    """Unit tests for counting privileged roles per user."""

    def test_no_roles(self) -> None:
        count = compute_privileged_role_count("u1", [])
        assert count == 0

    def test_one_privileged_role(self) -> None:
        roles = [_make_role_assignment("u1", "Global Administrator")]
        count = compute_privileged_role_count("u1", roles)
        assert count == 1

    def test_multiple_privileged_roles(self) -> None:
        roles = [
            _make_role_assignment("u1", "Global Administrator"),
            _make_role_assignment("u1", "Privileged Role Administrator"),
        ]
        count = compute_privileged_role_count("u1", roles)
        assert count == 2

    def test_non_privileged_roles_are_not_counted(self) -> None:
        roles = [
            _make_role_assignment("u1", "Reports Reader"),
            _make_role_assignment("u1", "Security Reader"),
        ]
        count = compute_privileged_role_count("u1", roles)
        assert count == 0

    def test_mixed_roles(self) -> None:
        roles = [
            _make_role_assignment("u1", "Global Administrator"),
            _make_role_assignment("u1", "Reports Reader"),
        ]
        count = compute_privileged_role_count("u1", roles)
        assert count == 1


# ---------------------------------------------------------------------------
# Integration-style tests for preprocess_dataset
# ---------------------------------------------------------------------------


class TestPreprocessDataset:
    """End-to-end tests for the main preprocess_dataset function."""

    def test_simple_dataset_returns_one_record(self, simple_dataset: dict) -> None:
        results = preprocess_dataset(simple_dataset)
        assert len(results) == 1

    def test_features_for_overprivileged_user(self, simple_dataset: dict) -> None:
        """A user with Global Admin and low sign-in activity should be flagged."""
        results = preprocess_dataset(simple_dataset)
        feat = results[0]
        assert feat["user_id"] == "u1"
        assert feat["display_name"] == "Alice"
        assert feat["days_since_last_signin"] is not None
        assert feat["role_tiers"] == ["critical"]
        assert feat["privileged_role_count"] == 1
        # Expect days > 0 because sign-in is far before now
        assert feat["days_since_last_signin"] > 0

    def test_group_inherited_role_detection(
        self, dataset_with_group_and_inherited_role: dict
    ) -> None:
        """User with inherited role should have assignment_type recorded."""
        results = preprocess_dataset(dataset_with_group_and_inherited_role)
        # Find Bob (u1)
        bob = next(r for r in results if r["user_id"] == "u1")
        assert bob["assignment_types"] == ["group"]
        # Carol (u2) has direct
        carol = next(r for r in results if r["user_id"] == "u2")
        assert carol["assignment_types"] == ["direct"]

    def test_user_with_no_signin_logs(self) -> None:
        """A user with no sign-in logs should have days_since_last_signin = None."""
        dataset = {
            "users": [_make_user("u3", "Charlie")],
            "roleAssignments": [],
            "signInLogs": [],
            "groups": [],
        }
        results = preprocess_dataset(dataset)
        feat = results[0]
        assert feat["days_since_last_signin"] is None
        assert feat["privileged_role_count"] == 0

    def test_user_with_multiple_roles_and_logs(self) -> None:
        """User with multiple roles and sign-in logs should have all features."""
        dataset = {
            "users": [_make_user("u4", "Diana")],
            "roleAssignments": [
                _make_role_assignment("u4", "Global Administrator"),
                _make_role_assignment("u4", "User Administrator"),
            ],
            "signInLogs": [
                _make_signin_log("u4", "2024-09-01T10:00:00Z"),
                _make_signin_log("u4", "2024-11-15T08:00:00Z"),
            ],
            "groups": [],
        }
        results = preprocess_dataset(dataset)
        feat = results[0]
        assert feat["privileged_role_count"] == 2
        assert sorted(feat["role_tiers"]) == ["critical", "high"]
        # days_since_last_signin computed from latest sign-in
        # We'll just assert it's a positive integer
        assert isinstance(feat["days_since_last_signin"], int)

    def test_dataset_missing_fields_raises_error(self) -> None:
        """Incomplete dataset should raise a ValueError."""
        with pytest.raises((ValueError, KeyError)):
            preprocess_dataset(
                {"users": [], "roleAssignments": []}
            )  # missing signInLogs

    def test_empty_users_returns_empty_list(self) -> None:
        """A dataset with no users should return an empty list."""
        dataset = {
            "users": [],
            "roleAssignments": [],
            "signInLogs": [],
            "groups": [],
        }
        results = preprocess_dataset(dataset)
        assert results == []

    def test_many_users_performance(self) -> None:
        """Process a larger dataset without errors (smoke test)."""
        users = [_make_user(f"u{i}", f"User{i}") for i in range(100)]
        assignments = [
            _make_role_assignment(f"u{i}", "Security Reader") for i in range(50)
        ]
        logs = [_make_signin_log(f"u{i}", "2024-10-01T10:00:00Z") for i in range(80)]
        dataset = {
            "users": users,
            "roleAssignments": assignments,
            "signInLogs": logs,
            "groups": [],
        }
        results = preprocess_dataset(dataset)
        assert len(results) == 100
