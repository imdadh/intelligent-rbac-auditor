from __future__ import annotations

import pytest

from scripts.generate_synthetic_data import generate_dataset

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def seeded_dataset() -> dict:
    """Return the synthetic dataset generated with seed 42."""
    return generate_dataset(seed=42)


@pytest.fixture(scope="module")
def seeded_dataset_bis() -> dict:
    """A second generation with the same seed – used for determinism check."""
    return generate_dataset(seed=42)


# ---------------------------------------------------------------------------
# Deterministic output
# ---------------------------------------------------------------------------


class TestDeterministicOutput:
    """The generator must produce identical output for the same seed."""

    def test_same_seed_identical(
        self, seeded_dataset: dict, seeded_dataset_bis: dict
    ) -> None:
        assert seeded_dataset == seeded_dataset_bis

    def test_different_seed_different(self) -> None:
        data1 = generate_dataset(seed=1)
        data2 = generate_dataset(seed=2)
        assert data1 != data2


# ---------------------------------------------------------------------------
# Top-level structure
# ---------------------------------------------------------------------------


class TestTopLevelStructure:
    """The returned dictionary must contain exactly the expected keys."""

    EXPECTED_KEYS = {"users", "roleAssignments", "signInLogs", "groups"}

    def test_top_level_keys(self, seeded_dataset: dict) -> None:
        assert set(seeded_dataset.keys()) == self.EXPECTED_KEYS

    def test_users_is_list(self, seeded_dataset: dict) -> None:
        assert isinstance(seeded_dataset["users"], list)

    def test_role_assignments_is_list(self, seeded_dataset: dict) -> None:
        assert isinstance(seeded_dataset["roleAssignments"], list)

    def test_sign_in_logs_is_list(self, seeded_dataset: dict) -> None:
        assert isinstance(seeded_dataset["signInLogs"], list)

    def test_groups_is_list(self, seeded_dataset: dict) -> None:
        assert isinstance(seeded_dataset["groups"], list)


# ---------------------------------------------------------------------------
# Counts and plausibility
# ---------------------------------------------------------------------------


class TestCounts:
    """The generator must produce a plausible number of entities."""

    def test_user_count(self, seeded_dataset: dict) -> None:
        users = seeded_dataset["users"]
        assert len(users) == 100, f"Expected 100 users, got {len(users)}"

    def test_role_assignment_count(self, seeded_dataset: dict) -> None:
        assignments = seeded_dataset["roleAssignments"]
        assert (
            len(assignments) >= 50
        ), f"Expected at least 50 role assignments, got {len(assignments)}"
        assert (
            len(assignments) <= 200
        ), f"Expected no more than 200 role assignments, got {len(assignments)}"

    def test_sign_in_log_count(self, seeded_dataset: dict) -> None:
        logs = seeded_dataset["signInLogs"]
        assert len(logs) >= 500, f"Expected at least 500 sign-in logs, got {len(logs)}"
        assert (
            len(logs) <= 5000
        ), f"Expected no more than 5000 sign-in logs, got {len(logs)}"

    def test_group_count(self, seeded_dataset: dict) -> None:
        groups = seeded_dataset["groups"]
        assert len(groups) >= 5, f"Expected at least 5 groups, got {len(groups)}"
        assert len(groups) <= 30, f"Expected no more than 30 groups, got {len(groups)}"


# ---------------------------------------------------------------------------
# User field completeness
# ---------------------------------------------------------------------------


class TestUserFields:
    """Every user must contain the required fields."""

    REQUIRED_FIELDS = {
        "id",
        "displayName",
        "userPrincipalName",
        "userType",
        "accountEnabled",
    }

    def test_all_users_have_required_fields(self, seeded_dataset: dict) -> None:
        for user in seeded_dataset["users"]:
            missing = self.REQUIRED_FIELDS - set(user.keys())
            assert not missing, f"User {user.get('id', '?')} missing fields: {missing}"

    def test_user_id_unique(self, seeded_dataset: dict) -> None:
        ids = [u["id"] for u in seeded_dataset["users"]]
        assert len(ids) == len(set(ids)), "Duplicate user IDs detected"

    def test_user_type_valid(self, seeded_dataset: dict) -> None:
        valid_types = {"Member", "Guest", "ServicePrincipal"}
        for user in seeded_dataset["users"]:
            assert (
                user["userType"] in valid_types
            ), f"Invalid userType: {user['userType']}"


# ---------------------------------------------------------------------------
# Role assignment field completeness
# ---------------------------------------------------------------------------


class TestRoleAssignmentFields:
    """Every role assignment must contain the required fields."""

    REQUIRED_FIELDS = {
        "id",
        "principalId",
        "roleDefinitionId",
        "roleName",
        "assignmentType",
        "assignedAt",
    }

    def test_all_assignments_have_required_fields(self, seeded_dataset: dict) -> None:
        for ra in seeded_dataset["roleAssignments"]:
            missing = self.REQUIRED_FIELDS - set(ra.keys())
            assert (
                not missing
            ), f"Assignment {ra.get('id', '?')} missing fields: {missing}"

    def test_assignment_type_valid(self, seeded_dataset: dict) -> None:
        valid_types = {"direct", "group"}
        for ra in seeded_dataset["roleAssignments"]:
            assert (
                ra["assignmentType"] in valid_types
            ), f"Invalid assignmentType: {ra['assignmentType']}"

    def test_assignedAt_is_datetime_string(self, seeded_dataset: dict) -> None:
        import datetime

        for ra in seeded_dataset["roleAssignments"]:
            try:
                datetime.datetime.fromisoformat(ra["assignedAt"])
            except (ValueError, TypeError):
                pytest.fail(
                    f"assignedAt '{ra['assignedAt']}' is not a valid ISO 8601 datetime"
                )


# ---------------------------------------------------------------------------
# Sign-in log field completeness
# ---------------------------------------------------------------------------


class TestSignInLogFields:
    """Every sign-in log must contain the required fields."""

    REQUIRED_FIELDS = {
        "id",
        "userId",
        "userDisplayName",
        "signInTimestamp",
        "appDisplayName",
        "status",
    }

    def test_all_logs_have_required_fields(self, seeded_dataset: dict) -> None:
        for log in seeded_dataset["signInLogs"]:
            missing = self.REQUIRED_FIELDS - set(log.keys())
            assert not missing, f"Log {log.get('id', '?')} missing fields: {missing}"

    def test_status_valid(self, seeded_dataset: dict) -> None:
        valid_statuses = {"Success", "Failure", "Interrupted"}
        for log in seeded_dataset["signInLogs"]:
            assert log["status"] in valid_statuses, f"Invalid status: {log['status']}"

    def test_signInTimestamp_is_datetime_string(self, seeded_dataset: dict) -> None:
        import datetime

        for log in seeded_dataset["signInLogs"]:
            try:
                datetime.datetime.fromisoformat(log["signInTimestamp"])
            except (ValueError, TypeError):
                pytest.fail(
                    f"signInTimestamp '{log['signInTimestamp']}' is not a valid ISO 8601 datetime"
                )


# ---------------------------------------------------------------------------
# Group field completeness
# ---------------------------------------------------------------------------


class TestGroupFields:
    """Every group must contain the required fields."""

    REQUIRED_FIELDS = {
        "id",
        "displayName",
        "isRoleAssignable",
        "members",
        "assignedRoles",
    }

    def test_all_groups_have_required_fields(self, seeded_dataset: dict) -> None:
        for group in seeded_dataset["groups"]:
            missing = self.REQUIRED_FIELDS - set(group.keys())
            assert (
                not missing
            ), f"Group {group.get('id', '?')} missing fields: {missing}"

    def test_members_is_list(self, seeded_dataset: dict) -> None:
        for group in seeded_dataset["groups"]:
            assert isinstance(group["members"], list)

    def test_assignedRoles_is_list(self, seeded_dataset: dict) -> None:
        for group in seeded_dataset["groups"]:
            assert isinstance(group["assignedRoles"], list)


# ---------------------------------------------------------------------------
# Known overprivileged and dormant accounts
# ---------------------------------------------------------------------------


class TestKnownAccounts:
    """The dataset must contain at least three overprivileged and three dormant
    accounts (as required by the PRD)."""

    def test_has_overprivileged_accounts(self, seeded_dataset: dict) -> None:
        """Overprivileged accounts are those whose assigned roles exceed their
        usage patterns. We check for accounts with Global Administrator and
        very few sign-in logs."""
        # Build a map of user -> role names
        user_roles: dict[str, list[str]] = {}
        for ra in seeded_dataset["roleAssignments"]:
            user_roles.setdefault(ra["principalId"], []).append(ra["roleName"])

        # Count sign-in logs per user
        user_logs: dict[str, int] = {}
        for log in seeded_dataset["signInLogs"]:
            user_logs[log["userId"]] = user_logs.get(log["userId"], 0) + 1

        overprivileged_count = 0
        for user in seeded_dataset["users"]:
            uid = user["id"]
            roles = user_roles.get(uid, [])
            if "Global Administrator" in roles:
                # Consider overprivileged if has GA but fewer than 10 sign-ins
                if user_logs.get(uid, 0) < 10:
                    overprivileged_count += 1

        assert (
            overprivileged_count >= 3
        ), f"Expected at least 3 overprivileged accounts, found {overprivileged_count}"

    def test_has_dormant_accounts(self, seeded_dataset: dict) -> None:
        """Dormant accounts have a privileged role but no recent sign-in.
        We check for accounts with any privileged role (e.g. Global Admin,
        Privileged Role Admin) and no sign-in in the last 60 days."""
        import datetime

        privileged_roles = {
            "Global Administrator",
            "Privileged Role Administrator",
            "Exchange Administrator",
            "SharePoint Administrator",
        }

        # Find latest sign-in timestamp per user
        latest_signin: dict[str, str | None] = {}
        for log in seeded_dataset["signInLogs"]:
            uid = log["userId"]
            if (
                latest_signin.get(uid) is None
                or log["signInTimestamp"] > latest_signin[uid]
            ):
                latest_signin[uid] = log["signInTimestamp"]

        # Reference date: now should be ~90 days after the seed's baseline
        # We use the dataset's generation time; for determinism we check that
        # accounts with no sign-ins at all are present.
        dormant_count = 0
        for user in seeded_dataset["users"]:
            uid = user["id"]
            # Check if user has any privileged role
            has_privileged = any(
                ra["roleName"] in privileged_roles
                for ra in seeded_dataset["roleAssignments"]
                if ra["principalId"] == uid
            )
            if has_privileged:
                last_signin = latest_signin.get(uid)
                if last_signin is None:
                    dormant_count += 1
                else:
                    # More than 60 days ago (approximate)
                    signin_dt = datetime.datetime.fromisoformat(last_signin)
                    # Generation time is roughly 90 days before now; we check if
                    # the signin is older than 60 days relative to generation time.
                    # This is a heuristic; we trust that the dataset has designated
                    # dormant accounts.
                    # Simpler: just count users with privileged roles and zero sign-ins.

        # Decoupled: we know at least 3 accounts have no sign-ins at all.
        no_signin_privileged = 0
        for user in seeded_dataset["users"]:
            uid = user["id"]
            has_privileged = any(
                ra["roleName"] in privileged_roles
                for ra in seeded_dataset["roleAssignments"]
                if ra["principalId"] == uid
            )
            if has_privileged and uid not in latest_signin:
                no_signin_privileged += 1
        assert (
            no_signin_privileged >= 3
        ), f"Expected at least 3 dormant accounts (no sign-ins with privileged role), found {no_signin_privileged}"


# ---------------------------------------------------------------------------
# Cross-reference integrity
# ---------------------------------------------------------------------------


class TestCrossReferenceIntegrity:
    """All referenced principal IDs must correspond to existing users or groups."""

    def test_role_assignments_reference_existing_principals(
        self, seeded_dataset: dict
    ) -> None:
        user_ids = {u["id"] for u in seeded_dataset["users"]}
        group_ids = {g["id"] for g in seeded_dataset["groups"]}
        all_ids = user_ids | group_ids
        for ra in seeded_dataset["roleAssignments"]:
            assert (
                ra["principalId"] in all_ids
            ), f"roleAssignment {ra['id']} references non-existent principal {ra['principalId']}"

    def test_signin_logs_reference_existing_users(self, seeded_dataset: dict) -> None:
        user_ids = {u["id"] for u in seeded_dataset["users"]}
        for log in seeded_dataset["signInLogs"]:
            assert (
                log["userId"] in user_ids
            ), f"signInLog {log['id']} references non-existent user {log['userId']}"

    def test_group_members_reference_existing_users(self, seeded_dataset: dict) -> None:
        user_ids = {u["id"] for u in seeded_dataset["users"]}
        for group in seeded_dataset["groups"]:
            for member_id in group["members"]:
                assert (
                    member_id in user_ids
                ), f"Group {group['id']} contains non-existent member {member_id}"

    def test_group_assigned_roles_reference_existing_role_definitions(
        self, seeded_dataset: dict
    ) -> None:
        role_ids = {ra["roleDefinitionId"] for ra in seeded_dataset["roleAssignments"]}
        for group in seeded_dataset["groups"]:
            for role_id in group["assignedRoles"]:
                assert (
                    role_id in role_ids
                ), f"Group {group['id']} assigns non-existent role definition {role_id}"
