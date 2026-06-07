"""Unit tests that verify the initial Alembic migration module is well-formed.

These tests do not require a live database connection.  They import the
migration module directly and inspect its structure to confirm:

- The revision identifier and chain metadata are set correctly.
- The ``upgrade`` and ``downgrade`` callables exist and accept no arguments.
- All expected table names are referenced inside the upgrade function source,
  confirming the DDL covers the full schema.
- The enum value sets match the values defined in the SQLAlchemy models.
- All expected indexes are created in the upgrade function.
- The module-level ENUM helper objects have the correct names and
  ``create_type=False`` to prevent Alembic from double-creating types.

Running these checks in CI catches accidental edits to the migration file
(e.g. a rename or deletion of a column block) before a live database is
involved.
"""

from __future__ import annotations

import importlib
import inspect
import types

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MIGRATION_MODULE_PATH = "migrations.versions.20250115_000000_initial_schema"


@pytest.fixture(scope="module")
def migration() -> types.ModuleType:
    """Import and return the initial schema migration module."""
    return importlib.import_module(MIGRATION_MODULE_PATH)


# ---------------------------------------------------------------------------
# Revision metadata
# ---------------------------------------------------------------------------


class TestRevisionMetadata:
    """The migration chain identifiers must be set to the expected values."""

    def test_revision_id_is_set(self, migration: types.ModuleType) -> None:
        assert hasattr(migration, "revision")
        assert isinstance(migration.revision, str)
        assert migration.revision  # non-empty

    def test_down_revision_is_none(self, migration: types.ModuleType) -> None:
        """This is the root migration — it must have no predecessor."""
        assert migration.down_revision is None

    def test_branch_labels_is_none(self, migration: types.ModuleType) -> None:
        assert migration.branch_labels is None

    def test_depends_on_is_none(self, migration: types.ModuleType) -> None:
        assert migration.depends_on is None

    def test_revision_id_value(self, migration: types.ModuleType) -> None:
        assert migration.revision == "20250115000000"


# ---------------------------------------------------------------------------
# Callable interface
# ---------------------------------------------------------------------------


class TestCallableInterface:
    """upgrade() and downgrade() must be present and callable with no required args."""

    def test_upgrade_is_callable(self, migration: types.ModuleType) -> None:
        assert callable(getattr(migration, "upgrade", None))

    def test_downgrade_is_callable(self, migration: types.ModuleType) -> None:
        assert callable(getattr(migration, "downgrade", None))

    def test_upgrade_takes_no_required_arguments(self, migration: types.ModuleType) -> None:
        sig = inspect.signature(migration.upgrade)
        required = [
            p
            for p in sig.parameters.values()
            if p.default is inspect.Parameter.empty
            and p.kind
            not in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            )
        ]
        assert len(required) == 0

    def test_downgrade_takes_no_required_arguments(self, migration: types.ModuleType) -> None:
        sig = inspect.signature(migration.downgrade)
        required = [
            p
            for p in sig.parameters.values()
            if p.default is inspect.Parameter.empty
            and p.kind
            not in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            )
        ]
        assert len(required) == 0


# ---------------------------------------------------------------------------
# Table coverage in upgrade source
# ---------------------------------------------------------------------------


class TestUpgradeTableCoverage:
    """The upgrade function's source must reference all four expected table names."""

    EXPECTED_TABLES = {"datasets", "audits", "findings", "query_logs"}

    def _upgrade_source(self, migration: types.ModuleType) -> str:
        return inspect.getsource(migration.upgrade)

    @pytest.mark.parametrize("table_name", sorted(EXPECTED_TABLES))
    def test_table_name_present_in_upgrade(
        self, migration: types.ModuleType, table_name: str
    ) -> None:
        source = self._upgrade_source(migration)
        assert (
            table_name in source
        ), f"Expected table '{table_name}' to be referenced in upgrade() but it was not found."


# ---------------------------------------------------------------------------
# Downgrade table coverage
# ---------------------------------------------------------------------------


class TestDowngradeTableCoverage:
    """The downgrade function's source must reference all four expected table names."""

    EXPECTED_TABLES = {"datasets", "audits", "findings", "query_logs"}

    def _downgrade_source(self, migration: types.ModuleType) -> str:
        return inspect.getsource(migration.downgrade)

    @pytest.mark.parametrize("table_name", sorted(EXPECTED_TABLES))
    def test_table_name_present_in_downgrade(
        self, migration: types.ModuleType, table_name: str
    ) -> None:
        source = self._downgrade_source(migration)
        assert (
            table_name in source
        ), f"Expected table '{table_name}' to be referenced in downgrade() but it was not found."


# ---------------------------------------------------------------------------
# Enum value coverage
# ---------------------------------------------------------------------------


class TestEnumValueCoverage:
    """All enum values defined in the models must appear in the migration source."""

    AUDIT_STATUS_VALUES = {"pending", "running", "completed", "failed"}
    FINDING_CATEGORY_VALUES = {"overprivileged", "dormant_privileged"}
    FINDING_SEVERITY_VALUES = {"critical", "high", "medium", "low"}

    def _upgrade_source(self, migration: types.ModuleType) -> str:
        return inspect.getsource(migration.upgrade)

    @pytest.mark.parametrize("value", sorted(AUDIT_STATUS_VALUES))
    def test_audit_status_value_present(self, migration: types.ModuleType, value: str) -> None:
        assert value in self._upgrade_source(migration)

    @pytest.mark.parametrize("value", sorted(FINDING_CATEGORY_VALUES))
    def test_finding_category_value_present(self, migration: types.ModuleType, value: str) -> None:
        assert value in self._upgrade_source(migration)

    @pytest.mark.parametrize("value", sorted(FINDING_SEVERITY_VALUES))
    def test_finding_severity_value_present(self, migration: types.ModuleType, value: str) -> None:
        assert value in self._upgrade_source(migration)


# ---------------------------------------------------------------------------
# Index coverage in upgrade source
# ---------------------------------------------------------------------------


class TestIndexCoverage:
    """The upgrade function must create the six indexes documented in the migration header."""

    EXPECTED_INDEXES = {
        "ix_audits_dataset_id",
        "ix_audits_status",
        "ix_findings_audit_id",
        "ix_findings_category",
        "ix_findings_severity",
        "ix_query_logs_dataset_id",
    }

    def _upgrade_source(self, migration: types.ModuleType) -> str:
        return inspect.getsource(migration.upgrade)

    @pytest.mark.parametrize("index_name", sorted(EXPECTED_INDEXES))
    def test_index_present_in_upgrade(self, migration: types.ModuleType, index_name: str) -> None:
        source = self._upgrade_source(migration)
        assert (
            index_name in source
        ), f"Expected index '{index_name}' to be created in upgrade() but it was not found."


# ---------------------------------------------------------------------------
# Enum helper objects
# ---------------------------------------------------------------------------


class TestEnumHelperObjects:
    """The module-level ENUM helper objects must be configured correctly."""

    def test_audit_status_enum_name(self, migration: types.ModuleType) -> None:
        assert migration.audit_status_enum.name == "audit_status"

    def test_finding_category_enum_name(self, migration: types.ModuleType) -> None:
        assert migration.finding_category_enum.name == "finding_category"

    def test_finding_severity_enum_name(self, migration: types.ModuleType) -> None:
        assert migration.finding_severity_enum.name == "finding_severity"

    def test_audit_status_enum_create_type_false(self, migration: types.ModuleType) -> None:
        """create_type=False is required; the type is created manually via raw SQL."""
        assert migration.audit_status_enum.create_type is False

    def test_finding_category_enum_create_type_false(self, migration: types.ModuleType) -> None:
        assert migration.finding_category_enum.create_type is False

    def test_finding_severity_enum_create_type_false(self, migration: types.ModuleType) -> None:
        assert migration.finding_severity_enum.create_type is False


# ---------------------------------------------------------------------------
# Column-level spot checks via source inspection
# ---------------------------------------------------------------------------


class TestColumnSpotChecks:
    """Spot-check that key column names and constraints appear in the upgrade source."""

    def _upgrade_source(self, migration: types.ModuleType) -> str:
        return inspect.getsource(migration.upgrade)

    @pytest.mark.parametrize(
        "column_name",
        [
            # datasets columns
            "raw_data",
            "user_count",
            "role_count",
            # audits columns
            "dataset_id",
            "status",
            "parameters",
            "summary",
            "started_at",
            "completed_at",
            # findings columns
            "audit_id",
            "category",
            "severity",
            "principal_id",
            "principal_name",
            "principal_type",
            "role_assignments",
            "evidence",
            "remediation",
            "narrative",
            # query_logs columns
            "question",
            "structured_response",
            "natural_language_response",
        ],
    )
    def test_column_present_in_upgrade(self, migration: types.ModuleType, column_name: str) -> None:
        source = self._upgrade_source(migration)
        assert (
            column_name in source
        ), f"Expected column '{column_name}' to appear in upgrade() but it was not found."

    def test_cascade_delete_present_for_audits_fk(self, migration: types.ModuleType) -> None:
        """Foreign keys with ON DELETE CASCADE must be explicit in the migration."""
        source = self._upgrade_source(migration)
        assert "CASCADE" in source

    def test_gen_random_uuid_used_as_server_default(self, migration: types.ModuleType) -> None:
        """UUID primary keys should have gen_random_uuid() as the server-side default."""
        source = self._upgrade_source(migration)
        assert "gen_random_uuid()" in source

    def test_jsonb_used_for_json_columns(self, migration: types.ModuleType) -> None:
        """JSON storage should use JSONB rather than plain JSON for performance."""
        source = self._upgrade_source(migration)
        assert "JSONB" in source
