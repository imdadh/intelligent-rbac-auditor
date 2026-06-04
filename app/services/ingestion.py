"""Dataset ingestion service — validate, parse, and persist Azure AD snapshot JSON.

This module contains the business logic for accepting a raw Azure AD tenant
snapshot (as a Python dict parsed from a JSON payload), validating its
structure against the canonical schema defined in
``app.schemas.dataset_schema``, enforcing cross-reference invariants,
computing derived metadata (e.g. user count), and writing a ``Dataset``
row to PostgreSQL.

Every public function in this module accepts an active SQLAlchemy ``Session``
so that callers (API route handlers, background tasks, seed scripts) control
the transaction lifecycle.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models.dataset import Dataset
from app.schemas.dataset_schema import AzureADDatasetPayload

logger = logging.getLogger(__name__)


class DatasetIngestionError(ValueError):
    """Raised when the supplied dataset fails validation or cross-reference checks.

    The ``message`` attribute contains a human-readable explanation suitable
    for returning to the API caller as a 422 error detail.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_cross_references(payload: AzureADDatasetPayload) -> None:
    """Enforce cross-reference invariants on the parsed payload.

    The following rules are checked (see PRD FR-2 for the full list):

    1. Every ``roleAssignments[].principalId`` matches a ``users[].id``
       or a ``groups[].id``.
    2. Every ``signInLogs[].userId`` matches a ``users[].id``.
    3. Every ``groups[].members`` element matches a ``users[].id``.
    4. When ``roleAssignments[].assignmentType == "group"`` the
       ``assignedVia`` field must be non-null and should correspond to
       a ``groups[].displayName`` (warn-only; not fatal).

    Parameters
    ----------
    payload:
        The fully parsed and type-validated dataset payload.

    Raises
    ------
    DatasetIngestionError
        If any invariant is violated.
    """
    user_ids: set[str] = {u.id for u in payload.users}
    group_ids: set[str] = {g.id for g in payload.groups}
    group_display_names: set[str] = {g.displayName for g in payload.groups}

    # 1. roleAssignments[].principalId
    for i, ra in enumerate(payload.roleAssignments):
        if ra.principalId not in user_ids and ra.principalId not in group_ids:
            raise DatasetIngestionError(
                f"roleAssignments[{i}].principalId '{ra.principalId}' "
                "does not reference any user or group in the dataset."
            )

    # 2. signInLogs[].userId
    for i, log in enumerate(payload.signInLogs):
        if log.userId not in user_ids:
            raise DatasetIngestionError(
                f"signInLogs[{i}].userId '{log.userId}' "
                "does not reference any user in the dataset."
            )

    # 3. groups[].members
    for i, group in enumerate(payload.groups):
        for j, member_id in enumerate(group.members):
            if member_id not in user_ids:
                raise DatasetIngestionError(
                    f"groups[{i}].members[{j}] '{member_id}' "
                    "does not reference any user in the dataset."
                )

    # 4. group-inherited assignment should have a matching group display name
    for i, ra in enumerate(payload.roleAssignments):
        if ra.assignmentType == "group":
            if ra.assignedVia is None:
                raise DatasetIngestionError(
                    f"roleAssignments[{i}] has assignmentType='group' but "
                    "assignedVia is null."
                )
            if ra.assignedVia not in group_display_names:
                logger.warning(
                    "roleAssignments[%d].assignedVia '%s' does not match "
                    "any group displayName in the dataset (non-fatal).",
                    i,
                    ra.assignedVia,
                )


def validate_dataset_data(data: dict[str, Any]) -> AzureADDatasetPayload:
    """Parse and validate a raw dataset dictionary against the canonical schema.

    This function performs two layers of validation:

    1. **Structural validation** — Pydantic parses the incoming dict into
       an ``AzureADDatasetPayload`` instance, verifying that all required
       fields are present, have the correct types, and conform to the
       controlled vocabularies (``userType``, ``assignmentType``, etc.).
    2. **Cross-reference validation** — Ensures foreign-key-style invariants
       are satisfied (every referenced principal ID exists, group inheritance
       has a non-null group name, etc.).

    Parameters
    ----------
    data:
        The raw dataset dictionary as received from the API endpoint.

    Returns
    -------
    AzureADDatasetPayload
        A validated Pydantic model instance.

    Raises
    ------
    DatasetIngestionError
        If validation fails at either layer. The message is suitable for
        returning to the API caller as a 422 error.
    """
    try:
        payload = AzureADDatasetPayload.model_validate(data)
    except ValidationError as exc:
        # Flatten the Pydantic error messages into a single human-readable
        # string. Pydantic v2 errors use a list of dicts under ``errors()``.
        error_details = []
        for err in exc.errors():
            loc = " -> ".join(str(p) for p in err.get("loc", []))
            msg = err.get("msg", "Unknown error")
            error_details.append(f"{loc}: {msg}")
        raise DatasetIngestionError(
            "Dataset validation failed:\n" + "\n".join(error_details)
        ) from exc

    _validate_cross_references(payload)
    return payload


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def ingest_dataset(
    name: str,
    data: dict[str, Any],
    db: Session,
) -> Dataset:
    """Validate and persist a dataset snapshot as a new ``Dataset`` row.

    This is the primary entry point called by the ``POST /api/v1/datasets``
    handler. It performs the full validation pipeline, inserts the record,
    and flushes the transaction so the caller receives a dataset with a
    database-generated UUID and timestamp.

    Parameters
    ----------
    name:
        A human-readable label for the dataset (e.g. the filename or a
        description like "Synthetic Azure AD Snapshot").
    data:
        The raw dataset dictionary (expected to conform to the
        ``AzureADDatasetPayload`` schema).
    db:
        An active SQLAlchemy ``Session``. The caller is responsible for
        committing (or rolling back) the transaction after this function
        returns.

    Returns
    -------
    Dataset
        The newly created ORM instance, already added to the session but
        **not** yet committed. The caller must commit the session for the
        change to be persisted permanently.

    Raises
    ------
    DatasetIngestionError
        If validation fails (see :func:`validate_dataset_data`).
    """
    payload = validate_dataset_data(data)

    user_count = len(payload.users)

    dataset = Dataset(
        name=name,
        raw_data=data,  # Store the original dict as JSON via SQLAlchemy
        user_count=user_count,
    )
    db.add(dataset)
    db.flush()  # Ensure the ID is populated without committing the outer txn

    logger.info(
        "Ingested dataset %s (name=%r, users=%d, roles=%d, logs=%d, groups=%d)",
        dataset.id,
        name,
        user_count,
        len(payload.roleAssignments),
        len(payload.signInLogs),
        len(payload.groups),
    )

    return dataset
