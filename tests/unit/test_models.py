from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import RelationshipProperty

from app.models.audit import Audit
from app.models.base import Base
from app.models.dataset import Dataset
from app.models.finding import Finding
from app.models.query_log import QueryLog

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_column_type(col: Column, expected_type: type) -> None:
    """Assert that a column's type is an instance of the given SQLAlchemy type."""
    assert isinstance(
        col.type, expected_type
    ), f"Column '{col.name}' has type {type(col.type).__name__}, expected {expected_type.__name__}"


def _assert_column_attributes(
    model_class: type,
    column_name: str,
    *,
    nullable: bool | None = None,
    primary_key: bool | None = None,
    default: object | None = None,
    server_default: object | None = None,
) -> None:
    col = model_class.__table__.columns[column_name]
    if nullable is not None:
        assert (
            col.nullable == nullable
        ), f"Column '{model_class.__tablename__}.{column_name}' nullable expected {nullable}, got {col.nullable}"
    if primary_key is not None:
        assert (
            col.primary_key == primary_key
        ), f"Column '{model_class.__tablename__}.{column_name}' primary_key expected {primary_key}, got {col.primary_key}"
    if default is not None:
        assert (
            col.default is not None and col.default.arg == default
        ), f"Column '{model_class.__tablename__}.{column_name}' default expected {default}, got {col.default.arg if col.default else None}"
    if server_default is not None:
        assert (
            col.server_default is not None
        ), f"Column '{model_class.__tablename__}.{column_name}' has no server_default"


def _has_relationship(model_class: type, attr_name: str) -> bool:
    return attr_name in model_class.__mapper__.relationships


def _get_relationship(model_class: type, attr_name: str) -> RelationshipProperty:
    return model_class.__mapper__.relationships[attr_name]


# ---------------------------------------------------------------------------
# Fixtures – model instances (instantiated without a session)
# ---------------------------------------------------------------------------


@pytest.fixture
def dataset_instance() -> Dataset:
    return Dataset(
        name="test-dataset",
        raw_data={"users": []},
        user_count=0,
        role_count=0,
    )


@pytest.fixture
def audit_instance(dataset_instance: Dataset) -> Audit:
    # We don't need to actually add to DB; just use the FK placeholder.
    return Audit(
        dataset_id=dataset_instance.id,
        status="pending",
        parameters={"threshold": 30},
    )


@pytest.fixture
def finding_instance(audit_instance: Audit) -> Finding:
    return Finding(
        audit_id=audit_instance.id,
        category="overprivileged",
        severity="high",
        principal_id="user-001",
        principal_name="Alice",
        principal_type="User",
        role_assignments=[{"roleName": "Global Admin"}],
        evidence={"daysSinceLastSignIn": 45},
        remediation="Remove Global Admin role",
        narrative="Alice has Global Admin but only needs User Admin.",
    )


@pytest.fixture
def query_log_instance(dataset_instance: Dataset) -> QueryLog:
    return QueryLog(
        dataset_id=dataset_instance.id,
        question="Show admins",
        structured_response={"results": []},
        natural_language_response="No results.",
    )


# ---------------------------------------------------------------------------
# Test Base
# ---------------------------------------------------------------------------


class TestBase:
    def test_declarative_base_has_metadata(self) -> None:
        assert Base.metadata is not None

    def test_declarative_base_has_registry(self) -> None:
        assert Base.registry is not None


# ---------------------------------------------------------------------------
# Test Dataset model
# ---------------------------------------------------------------------------


class TestDatasetModel:
    def test_tablename(self) -> None:
        assert Dataset.__tablename__ == "datasets"

    def test_column_id(self) -> None:
        col = Dataset.__table__.columns["id"]
        _assert_column_type(col, UUID)
        _assert_column_attributes(Dataset, "id", primary_key=True, nullable=False)

    def test_column_name(self) -> None:
        col = Dataset.__table__.columns["name"]
        _assert_column_type(col, String)
        _assert_column_attributes(Dataset, "name", nullable=False)

    def test_column_raw_data(self) -> None:
        col = Dataset.__table__.columns["raw_data"]
        _assert_column_type(col, JSONB)
        _assert_column_attributes(Dataset, "raw_data", nullable=False, default={})

    def test_column_user_count(self) -> None:
        col = Dataset.__table__.columns["user_count"]
        _assert_column_type(col, Integer)
        _assert_column_attributes(Dataset, "user_count", nullable=False, default=0)

    def test_column_role_count(self) -> None:
        col = Dataset.__table__.columns["role_count"]
        _assert_column_type(col, Integer)
        _assert_column_attributes(Dataset, "role_count", nullable=False, default=0)

    def test_column_created_at(self) -> None:
        col = Dataset.__table__.columns["created_at"]
        # server_default = func.now() -> we can check that a server_default exists
        assert col.server_default is not None, "created_at should have server_default"
        # nullable is effectively True but server_default fills it; we check server_default
        _assert_column_attributes(Dataset, "created_at", nullable=False)

    def test_relationship_audits(self) -> None:
        assert _has_relationship(Dataset, "audits")
        rel = _get_relationship(Dataset, "audits")
        assert rel.direction.name == "ONETOMANY"
        assert rel.argument == Audit

    def test_relationship_back_populates(self) -> None:
        rel = _get_relationship(Dataset, "audits")
        # The Audit relationship should have back_populates="audits"
        assert rel.back_populates == "audits"

    def test_instantiation(self, dataset_instance: Dataset) -> None:
        assert dataset_instance.name == "test-dataset"
        assert dataset_instance.user_count == 0
        assert dataset_instance.role_count == 0

    def test_partial_instantiation_defaults(self) -> None:
        """Instantiate with only required field(s); verify Python-level defaults."""
        d = Dataset(name="partial")
        assert d.raw_data == {}
        assert d.user_count == 0
        assert d.role_count == 0

    def test_str_representation(self, dataset_instance: Dataset) -> None:
        # __str__ or __repr__ may be defined; check it exists and returns string
        s = str(dataset_instance)
        assert "test-dataset" in s


# ---------------------------------------------------------------------------
# Test Audit model
# ---------------------------------------------------------------------------


class TestAuditModel:
    def test_tablename(self) -> None:
        assert Audit.__tablename__ == "audits"

    def test_column_id(self) -> None:
        col = Audit.__table__.columns["id"]
        _assert_column_type(col, UUID)
        _assert_column_attributes(Audit, "id", primary_key=True, nullable=False)

    def test_column_dataset_id(self) -> None:
        col = Audit.__table__.columns["dataset_id"]
        _assert_column_type(col, UUID)
        _assert_column_attributes(Audit, "dataset_id", nullable=False)
        # Verify ForeignKey
        assert len(col.foreign_keys) == 1
        fk = next(iter(col.foreign_keys))
        assert fk.column.table.name == "datasets"

    def test_column_status(self) -> None:
        col = Audit.__table__.columns["status"]
        _assert_column_type(col, String)
        _assert_column_attributes(Audit, "status", nullable=False, default="pending")

    def test_column_parameters(self) -> None:
        col = Audit.__table__.columns["parameters"]
        _assert_column_type(col, JSONB)
        _assert_column_attributes(Audit, "parameters", nullable=False, default={})

    def test_column_summary(self) -> None:
        col = Audit.__table__.columns["summary"]
        _assert_column_type(col, JSONB)
        _assert_column_attributes(Audit, "summary", nullable=True, default=None)

    def test_column_started_at(self) -> None:
        col = Audit.__table__.columns["started_at"]
        _assert_column_attributes(Audit, "started_at", nullable=True)

    def test_column_completed_at(self) -> None:
        col = Audit.__table__.columns["completed_at"]
        _assert_column_attributes(Audit, "completed_at", nullable=True)

    def test_column_created_at(self) -> None:
        col = Audit.__table__.columns["created_at"]
        assert col.server_default is not None
        _assert_column_attributes(Audit, "created_at", nullable=False)

    def test_relationship_dataset(self) -> None:
        assert _has_relationship(Audit, "dataset")
        rel = _get_relationship(Audit, "dataset")
        assert rel.direction.name == "MANYTOONE"
        assert rel.argument == Dataset

    def test_relationship_findings(self) -> None:
        assert _has_relationship(Audit, "findings")
        rel = _get_relationship(Audit, "findings")
        assert rel.direction.name == "ONETOMANY"
        assert rel.argument == Finding

    def test_relationship_back_populates(self) -> None:
        rel_dataset = _get_relationship(Audit, "dataset")
        assert rel_dataset.back_populates == "audits"
        rel_findings = _get_relationship(Audit, "findings")
        assert rel_findings.back_populates == "audit"

    def test_instantiation(self, audit_instance: Audit) -> None:
        assert audit_instance.status == "pending"
        assert audit_instance.parameters == {"threshold": 30}

    def test_partial_instantiation_defaults(self) -> None:
        """Instantiate with only dataset_id (UUID placeholder)."""
        a = Audit(dataset_id=audit_instance.dataset_id)
        assert a.status == "pending"
        assert a.parameters == {}
        assert a.summary is None

    def test_str_representation(self, audit_instance: Audit) -> None:
        s = str(audit_instance)
        assert "pending" in s


# ---------------------------------------------------------------------------
# Test Finding model
# ---------------------------------------------------------------------------


class TestFindingModel:
    def test_tablename(self) -> None:
        assert Finding.__tablename__ == "findings"

    def test_column_id(self) -> None:
        col = Finding.__table__.columns["id"]
        _assert_column_type(col, UUID)
        _assert_column_attributes(Finding, "id", primary_key=True, nullable=False)

    def test_column_audit_id(self) -> None:
        col = Finding.__table__.columns["audit_id"]
        _assert_column_type(col, UUID)
        _assert_column_attributes(Finding, "audit_id", nullable=False)
        fk = next(iter(col.foreign_keys))
        assert fk.column.table.name == "audits"
        # cascade
        assert "CASCADE" in str(list(col.foreign_keys)[0].ondelete)

    def test_column_category(self) -> None:
        col = Finding.__table__.columns["category"]
        _assert_column_type(col, String)
        _assert_column_attributes(Finding, "category", nullable=False)

    def test_column_severity(self) -> None:
        col = Finding.__table__.columns["severity"]
        _assert_column_type(col, String)
        _assert_column_attributes(Finding, "severity", nullable=False)

    def test_column_principal_id(self) -> None:
        col = Finding.__table__.columns["principal_id"]
        _assert_column_type(col, String)
        _assert_column_attributes(Finding, "principal_id", nullable=False)

    def test_column_principal_name(self) -> None:
        col = Finding.__table__.columns["principal_name"]
        _assert_column_type(col, String)
        _assert_column_attributes(Finding, "principal_name", nullable=False)

    def test_column_principal_type(self) -> None:
        col = Finding.__table__.columns["principal_type"]
        _assert_column_type(col, String)
        _assert_column_attributes(Finding, "principal_type", nullable=False, default="User")

    def test_column_role_assignments(self) -> None:
        col = Finding.__table__.columns["role_assignments"]
        _assert_column_type(col, JSONB)
        _assert_column_attributes(Finding, "role_assignments", nullable=False, default=[])

    def test_column_evidence(self) -> None:
        col = Finding.__table__.columns["evidence"]
        _assert_column_type(col, JSONB)
        _assert_column_attributes(Finding, "evidence", nullable=False, default={})

    def test_column_remediation(self) -> None:
        col = Finding.__table__.columns["remediation"]
        _assert_column_type(col, Text)
        _assert_column_attributes(Finding, "remediation", nullable=False, default="")

    def test_column_narrative(self) -> None:
        col = Finding.__table__.columns["narrative"]
        _assert_column_type(col, Text)
        _assert_column_attributes(Finding, "narrative", nullable=False, default="")

    def test_column_created_at(self) -> None:
        col = Finding.__table__.columns["created_at"]
        assert col.server_default is not None
        _assert_column_attributes(Finding, "created_at", nullable=False)

    def test_relationship_audit(self) -> None:
        # Findings belong to one audit
        assert _has_relationship(Finding, "audit")
        rel = _get_relationship(Finding, "audit")
        assert rel.direction.name == "MANYTOONE"
        assert rel.argument == Audit

    def test_relationship_back_populates(self) -> None:
        rel = _get_relationship(Finding, "audit")
        assert rel.back_populates == "findings"

    def test_instantiation(self, finding_instance: Finding) -> None:
        assert finding_instance.category == "overprivileged"
        assert finding_instance.severity == "high"
        assert finding_instance.principal_name == "Alice"

    def test_partial_instantiation_defaults(self) -> None:
        """Instantiate with a minimal set of required fields."""
        f = Finding(
            audit_id=finding_instance.audit_id,
            category="dormant_privileged",
            severity="medium",
            principal_id="user-002",
            principal_name="Bob",
        )
        assert f.principal_type == "User"
        assert f.role_assignments == []
        assert f.evidence == {}
        assert f.remediation == ""
        assert f.narrative == ""

    def test_str_representation(self, finding_instance: Finding) -> None:
        s = str(finding_instance)
        assert "overprivileged" in s


# ---------------------------------------------------------------------------
# Test QueryLog model
# ---------------------------------------------------------------------------


class TestQueryLogModel:
    def test_tablename(self) -> None:
        assert QueryLog.__tablename__ == "query_logs"

    def test_column_id(self) -> None:
        col = QueryLog.__table__.columns["id"]
        _assert_column_type(col, UUID)
        _assert_column_attributes(QueryLog, "id", primary_key=True, nullable=False)

    def test_column_dataset_id(self) -> None:
        col = QueryLog.__table__.columns["dataset_id"]
        _assert_column_type(col, UUID)
        _assert_column_attributes(QueryLog, "dataset_id", nullable=False)
        fk = next(iter(col.foreign_keys))
        assert fk.column.table.name == "datasets"

    def test_column_question(self) -> None:
        col = QueryLog.__table__.columns["question"]
        _assert_column_type(col, Text)
        _assert_column_attributes(QueryLog, "question", nullable=False)

    def test_column_structured_response(self) -> None:
        col = QueryLog.__table__.columns["structured_response"]
        _assert_column_type(col, JSONB)
        _assert_column_attributes(QueryLog, "structured_response", nullable=True)

    def test_column_natural_language_response(self) -> None:
        col = QueryLog.__table__.columns["natural_language_response"]
        _assert_column_type(col, Text)
        _assert_column_attributes(QueryLog, "natural_language_response", nullable=True)

    def test_column_created_at(self) -> None:
        col = QueryLog.__table__.columns["created_at"]
        assert col.server_default is not None
        _assert_column_attributes(QueryLog, "created_at", nullable=False)

    def test_relationship_dataset(self) -> None:
        assert _has_relationship(QueryLog, "dataset")
        rel = _get_relationship(QueryLog, "dataset")
        assert rel.direction.name == "MANYTOONE"
        assert rel.argument == Dataset

    def test_relationship_back_populates(self) -> None:
        rel = _get_relationship(QueryLog, "dataset")
        # The Dataset model does not have a back_populates for query_logs,
        # so this relationship does not have back_populates. We simply verify
        # that the attribute is None (or not set).
        # This checks that the relationship is correctly defined as unidirectional.
        # If a future commit adds back_populates, update this test.
        assert getattr(rel, "back_populates", None) is None

    def test_instantiation(self, query_log_instance: QueryLog) -> None:
        assert query_log_instance.question == "Show admins"
        assert query_log_instance.natural_language_response == "No results."

    def test_partial_instantiation_defaults(self) -> None:
        """Instantiate with required fields only."""
        q = QueryLog(
            dataset_id=query_log_instance.dataset_id,
            question="Test question",
        )
        assert q.structured_response is None
        assert q.natural_language_response is None

    def test_str_representation(self, query_log_instance: QueryLog) -> None:
        s = str(query_log_instance)
        assert "Show admins" in s
