"""Unit tests for the dataset ingestion service.

Tests cover:
- Schema validation of the top-level payload (valid data passes,
  missing required fields rejected, malformed role assignments rejected)
- Cross-reference validation (missing user reference, broken group lineage)
- Record count computation (user_count matches the number of users)
- The full ``ingest_dataset()`` path with a mocked SQLAlchemy session.
"""

from __future__ import annotations

import copy
from unittest.mock import MagicMock

import pytest

from app.models.dataset import Dataset
from app.schemas.dataset_schema import (
    AzureADDatasetPayload,
)
from app.services.ingestion import (
    DatasetIngestionError,
    ingest_dataset,
    validate_dataset_data,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def minimal_valid_payload() -> dict:
    """Return a dict that passes structural validation with one user, one role,
    one sign-in log, and no groups."""
    return {
        "users": [
            {
                "id": "user-1",
                "displayName": "Alice Johnson",
                "userPrincipalName": "alice@contoso.onmicrosoft.com",
                "userType": "Member",
                "accountEnabled": True,
            }
        ],
        "roleAssignments": [
            {
                "id": "ra-1",
                "principalId": "user-1",
                "roleDefinitionId": "62e90394-69f5-4237-9190-012177145e10",
                "roleName": "Global Administrator",
                "assignmentType": "direct",
                "assignedVia": None,
                "assignedAt": "2023-06-15T09:00:00Z",
            }
        ],
        "signInLogs": [
            {
                "id": "sl-1",
                "userId": "user-1",
                "userDisplayName": "Alice Johnson",
                "signInTimestamp": "2024-10-01T08:30:00Z",
                "appDisplayName": "Microsoft Azure Management",
                "status": "Success",
                "ipAddress": "203.0.113.42",
            }
        ],
        "groups": [],
    }


@pytest.fixture
def db_session() -> MagicMock:
    """Return a mock SQLAlchemy session."""
    session = MagicMock()
    # Simulate ``db.add`` storing the object and ``db.flush`` populating the ID.
    dataset = Dataset(
        name="test",
        raw_data={},
        user_count=0,
    )
    session.add.return_value = None
    session.flush.return_value = None
    # Make ``db.add`` capture the dataset object so we can inspect it.
    session.add.side_effect = lambda obj: None
    return session


# ---------------------------------------------------------------------------
# Tests: ``validate_dataset_data`` — structural validation
# ---------------------------------------------------------------------------


class TestValidateDatasetData:
    """Unit tests for the ``validate_dataset_data`` function."""

    def test_valid_data_passes(self, minimal_valid_payload: dict) -> None:
        """A well-formed payload should return a parsed ``AzureADDatasetPayload``."""
        payload = validate_dataset_data(minimal_valid_payload)
        assert isinstance(payload, AzureADDatasetPayload)
        assert len(payload.users) == 1
        assert payload.users[0].id == "user-1"

    def test_missing_users_key_raises_error(self) -> None:
        """Missing top-level 'users' must produce a ``DatasetIngestionError``."""
        data = {
            "roleAssignments": [],
            "signInLogs": [],
            "groups": [],
        }
        with pytest.raises(DatasetIngestionError, match="users"):
            validate_dataset_data(data)

    def test_missing_required_user_field_raises_error(
        self, minimal_valid_payload: dict
    ) -> None:
        """A user entry missing ``identifier`` should fail."""
        payload = copy.deepcopy(minimal_valid_payload)
        del payload["users"][0]["id"]  # required field in UserRecord is 'id'
        with pytest.raises(DatasetIngestionError, match="id"):
            validate_dataset_data(payload)

    def test_missing_required_role_field_raises_error(
        self, minimal_valid_payload: dict
    ) -> None:
        """A role assignment missing ``roleName`` should fail."""
        payload = copy.deepcopy(minimal_valid_payload)
        del payload["roleAssignments"][0]["roleName"]
        with pytest.raises(DatasetIngestionError, match="roleName"):
            validate_dataset_data(payload)

    def test_missing_required_role_id_raises_error(
        self, minimal_valid_payload: dict
    ) -> None:
        """A role assignment missing ``roleDefinitionId`` should fail."""
        payload = copy.deepcopy(minimal_valid_payload)
        del payload["roleAssignments"][0]["roleDefinitionId"]
        with pytest.raises(DatasetIngestionError, match="roleDefinitionId"):
            validate_dataset_data(payload)

    def test_missing_required_assignment_type_raises_error(
        self, minimal_valid_payload: dict
    ) -> None:
        """A role assignment missing ``assignmentType`` should fail."""
        payload = copy.deepcopy(minimal_valid_payload)
        del payload["roleAssignments"][0]["assignmentType"]
        with pytest.raises(DatasetIngestionError, match="assignmentType"):
            validate_dataset_data(payload)

    def test_invalid_assignment_type_raises_error(
        self, minimal_valid_payload: dict
    ) -> None:
        """An invalid ``assignmentType`` value should fail."""
        payload = copy.deepcopy(minimal_valid_payload)
        payload["roleAssignments"][0]["assignmentType"] = "invalid"
        with pytest.raises(DatasetIngestionError, match="assignmentType"):
            validate_dataset_data(payload)

    @pytest.mark.parametrize(
        "missing_field",
        [
            "signInTimestamp",
            "userId",
            "appDisplayName",
            "status",
        ],
    )
    def test_missing_required_signin_log_field_raises_error(
        self, minimal_valid_payload: dict, missing_field: str
    ) -> None:
        """A sign-in log missing a required field should fail."""
        payload = copy.deepcopy(minimal_valid_payload)
        del payload["signInLogs"][0][missing_field]
        with pytest.raises(DatasetIngestionError):
            validate_dataset_data(payload)

    def test_empty_users_array_passes(self) -> None:
        """An empty ``users`` array is valid (no findings, but schema-valid)."""
        data = {
            "users": [],
            "roleAssignments": [],
            "signInLogs": [],
            "groups": [],
        }
        payload = validate_dataset_data(data)
        assert len(payload.users) == 0


# ---------------------------------------------------------------------------
# Tests: ``validate_dataset_data`` — cross-reference validation
# ---------------------------------------------------------------------------


class TestCrossReferenceValidation:
    """Ensure cross-reference invariants are enforced."""

    def test_role_assignment_principal_id_not_found(
        self, minimal_valid_payload: dict
    ) -> None:
        """A role assignment referencing a non-existent user must fail."""
        payload = copy.deepcopy(minimal_valid_payload)
        payload["roleAssignments"][0]["principalId"] = "nonexistent-user"
        with pytest.raises(
            DatasetIngestionError, match="does not reference any user or group"
        ):
            validate_dataset_data(payload)

    def test_signin_log_user_id_not_found(self, minimal_valid_payload: dict) -> None:
        """A sign-in log referencing a non-existent user must fail."""
        payload = copy.deepcopy(minimal_valid_payload)
        payload["signInLogs"][0]["userId"] = "nonexistent-user"
        with pytest.raises(DatasetIngestionError, match="does not reference any user"):
            validate_dataset_data(payload)

    def test_group_member_not_found(self, minimal_valid_payload: dict) -> None:
        """A group member ID that does not exist in users must fail."""
        payload = copy.deepcopy(minimal_valid_payload)
        payload["groups"] = [
            {
                "id": "grp-1",
                "displayName": "Test Group",
                "isRoleAssignable": False,
                "members": ["nonexistent-user"],
                "assignedRoles": [],
            }
        ]
        with pytest.raises(DatasetIngestionError, match="does not reference any user"):
            validate_dataset_data(payload)

    def test_group_inherited_assignment_without_assigned_via(
        self, minimal_valid_payload: dict
    ) -> None:
        """A group-inherited assignment with ``assignedVia=None`` must fail."""
        payload = copy.deepcopy(minimal_valid_payload)
        # Add a group that the assignment can reference.
        payload["groups"] = [
            {
                "id": "grp-1",
                "displayName": "Tier0-Admins",
                "isRoleAssignable": True,
                "members": [],
                "assignedRoles": ["62e90394-69f5-4237-9190-012177145e10"],
            }
        ]
        payload["roleAssignments"][0]["assignmentType"] = "group"
        payload["roleAssignments"][0]["assignedVia"] = None
        with pytest.raises(DatasetIngestionError, match="assignedVia is null"):
            validate_dataset_data(payload)


# ---------------------------------------------------------------------------
# Tests: ``ingest_dataset`` — record count and persistence
# ---------------------------------------------------------------------------


class TestIngestDataset:
    """Tests for the full ingestion workflow with a mocked session."""

    def test_record_count_matches_user_count(
        self, minimal_valid_payload: dict, db_session: MagicMock
    ) -> None:
        """The returned ``Dataset`` object must have ``user_count`` equal to
        the number of users in the validated payload."""
        dataset = ingest_dataset(
            name="test-dataset",
            data=minimal_valid_payload,
            db=db_session,
        )
        assert dataset.user_count == len(minimal_valid_payload["users"])
        # Ensure the dataset was added to the session.
        db_session.add.assert_called_once()
        db_session.flush.assert_called_once()

    def test_record_count_with_multiple_users(self, db_session: MagicMock) -> None:
        """A payload with three users yields ``user_count=3``."""
        payload = {
            "users": [
                {
                    "id": "u1",
                    "displayName": "A",
                    "userPrincipalName": "a@c.com",
                    "userType": "Member",
                    "accountEnabled": True,
                },
                {
                    "id": "u2",
                    "displayName": "B",
                    "userPrincipalName": "b@c.com",
                    "userType": "Member",
                    "accountEnabled": False,
                },
                {
                    "id": "u3",
                    "displayName": "C",
                    "userPrincipalName": "c@c.com",
                    "userType": "ServicePrincipal",
                    "accountEnabled": True,
                },
            ],
            "roleAssignments": [],
            "signInLogs": [],
            "groups": [],
        }
        dataset = ingest_dataset(name="multi", data=payload, db=db_session)
        assert dataset.user_count == 3

    def test_invalid_data_raises_and_does_not_add(self, db_session: MagicMock) -> None:
        """If validation fails, the session must not be touched."""
        invalid_payload = {"roleAssignments": [], "signInLogs": [], "groups": []}
        with pytest.raises(DatasetIngestionError):
            ingest_dataset(name="bad", data=invalid_payload, db=db_session)
        db_session.add.assert_not_called()
        db_session.flush.assert_not_called()
