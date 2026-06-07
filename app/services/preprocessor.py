from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Azure AD built-in role tier classification
# ---------------------------------------------------------------------------
# Tier 0 — roles with tenant-wide administrative control
TIER_0_ROLES: set[str] = {
    "Global Administrator",
    "Privileged Role Administrator",
    "Privileged Authentication Administrator",
}

# Tier 1 — roles with broad but scoped administrative access
TIER_1_ROLES: set[str] = {
    "User Administrator",
    "Security Administrator",
    "Exchange Administrator",
    "SharePoint Administrator",
    "Compliance Administrator",
    "Helpdesk Administrator",
    "Application Administrator",
    "Cloud Application Administrator",
}

# Tier 2 — read-only or low-privilege roles
TIER_2_ROLES: set[str] = {
    "Directory Readers",
    "Security Reader",
    "Reports Reader",
    "Message Center Reader",
}


def _get_role_tier(role_name: str) -> str:
    """Return the tier label for a given Azure AD directory role.

    Classification follows the authorisation tiering model used in
    enterprise Entra ID deployments:

    - ``"critical"``  — Tier 0 (tenant-wide admin)
    - ``"high"``      — Tier 1 (broad admin)
    - ``"medium"``    — Tier 2 (read-only / limited)
    - ``"low"``       — Unknown or non-privileged role

    Parameters
    ----------
    role_name:
        The display name of the Azure AD directory role (e.g.
        ``"Global Administrator"``).

    Returns
    -------
    str
        One of ``"critical"``, ``"high"``, ``"medium"``, or ``"low"``.
    """
    if role_name in TIER_0_ROLES:
        return "critical"
    if role_name in TIER_1_ROLES:
        return "high"
    if role_name in TIER_2_ROLES:
        return "medium"
    # Roles not in the known list are considered low-privilege.
    # This includes custom roles and default user permissions.
    return "low"


def _get_highest_role_tier(role_names: list[str]) -> str:
    """Return the most privileged tier among a list of role names.

    Utility used to determine a principal's overall role tier based on
    the highest-risk role they hold.
    """
    tiers = [_get_role_tier(r) for r in role_names]
    # Order of precedence: critical > high > medium > low
    for target in ("critical", "high", "medium"):
        if target in tiers:
            return target
    return "low"


def preprocess_dataset(dataset: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Compute derived features for every principal in the dataset.

    The input *dataset* is the full Azure AD snapshot dict as ingested
    (via ``POST /api/v1/datasets``) and later retrieved from the database.
    It is expected to contain the following top-level keys:

    - ``"users"``       — list of user/service principal records
    - ``"roleAssignments"`` — list of role assignment records
    - ``"signInLogs"``  — list of sign-in log entries
    - ``"groups"``      — list of group definitions (unused directly but
                            role assignments may reference groups)
    - ``"_meta"``       (optional) — metadata dict that may include
      ``"snapshotDate"`` used to anchor time delta calculations.

    The method processes each principal and returns a dictionary keyed
    by ``principal_id``.  Each value is a dict with the following keys:

    - ``displayName``         — display name from the user record
    - ``userType``            — ``"Member"``, ``"Guest"``, or
                                ``"ServicePrincipal"``
    - ``days_since_last_sign_in`` — float or ``None`` if no sign-in logs
    - ``role_tier``           — most privileged tier among assigned roles
    - ``assignment_type``     — ``"direct"``, ``"group"``, ``"mixed"``,
                                or ``"none"``
    - ``privileged_role_count`` — number of assigned roles classified as
                                  Tier 0 or Tier 1 (i.e. critical or high)
    - ``roles``               — list of role names held by the principal

    Parameters
    ----------
    dataset:
        The full dataset dict (as stored in ``Dataset.raw_data``).

    Returns
    -------
    dict[str, dict[str, Any]]
        Pre-processed features per principal, ready to be passed to
        an LLM provider's ``analyze_findings`` method.
    """
    # ------------------------------------------------------------------
    # Resolve snapshot date — use the value embedded in the dataset if
    # present, otherwise fall back to the current UTC time.  All time
    # delta calculations are anchored to this timestamp.
    # ------------------------------------------------------------------
    meta = dataset.get("_meta", {})
    snapshot_date_str = meta.get("snapshotDate")
    if snapshot_date_str:
        try:
            snapshot_date = datetime.fromisoformat(snapshot_date_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            logger.warning(
                "Unable to parse _meta.snapshotDate '%s'; using current UTC time.",
                snapshot_date_str,
            )
            snapshot_date = datetime.now(UTC)
    else:
        snapshot_date = datetime.now(UTC)

    # Ensure the snapshot date is timezone-aware (UTC).
    if snapshot_date.tzinfo is None:
        snapshot_date = snapshot_date.replace(tzinfo=UTC)

    # ------------------------------------------------------------------
    # Build lookup structures
    # ------------------------------------------------------------------
    users: list[dict[str, Any]] = dataset.get("users", [])
    role_assignments: list[dict[str, Any]] = dataset.get("roleAssignments", [])
    sign_in_logs: list[dict[str, Any]] = dataset.get("signInLogs", [])

    # User ID -> user record
    user_map: dict[str, dict[str, Any]] = {}
    for u in users:
        user_id = u.get("id")
        if not user_id:
            continue
        user_map[user_id] = u

    # User ID -> list of role assignments
    user_role_map: dict[str, list[dict[str, Any]]] = {}
    for ra in role_assignments:
        pid = ra.get("principalId")
        if not pid:
            continue
        user_role_map.setdefault(pid, []).append(ra)

    # User ID -> latest sign-in timestamp (datetime or None)
    user_latest_signin: dict[str, datetime | None] = {}
    for log in sign_in_logs:
        user_id = log.get("userId")
        ts_str = log.get("signInTimestamp")
        if not user_id or not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        existing = user_latest_signin.get(user_id)
        if existing is None or ts > existing:
            user_latest_signin[user_id] = ts

    # ------------------------------------------------------------------
    # Build principal index (including service principals, guests).
    # Every user in ``users`` becomes a principal in the output.
    # ------------------------------------------------------------------
    result: dict[str, dict[str, Any]] = {}

    for user_id, user_record in user_map.items():
        display_name: str = user_record.get("displayName", "Unknown")
        user_type: str = user_record.get("userType", "Member")

        # --- Role information ---
        user_roles = user_role_map.get(user_id, [])
        role_names: list[str] = [ra.get("roleName", "Unknown") for ra in user_roles]
        assignment_types: set[str] = {ra.get("assignmentType", "direct") for ra in user_roles}

        if not assignment_types:
            assignment_type: str = "none"
        elif assignment_types == {"direct"}:
            assignment_type = "direct"
        elif assignment_types == {"group"}:
            assignment_type = "group"
        else:
            assignment_type = "mixed"

        # Count of privileged roles (Tier 0 or Tier 1)
        privileged_role_count: int = sum(
            1 for r in role_names if _get_role_tier(r) in ("critical", "high")
        )

        # Highest role tier among assigned roles
        if role_names:
            role_tier: str = _get_highest_role_tier(role_names)
        else:
            role_tier = "none"

        # --- Sign-in activity ---
        last_signin = user_latest_signin.get(user_id)
        if last_signin is not None:
            delta: timedelta = snapshot_date - last_signin
            days_since_last_sign_in: float | None = max(0.0, delta.total_seconds() / 86400.0)
        else:
            days_since_last_sign_in = None

        result[user_id] = {
            "displayName": display_name,
            "userType": user_type,
            "days_since_last_sign_in": days_since_last_sign_in,
            "role_tier": role_tier,
            "assignment_type": assignment_type,
            "privileged_role_count": privileged_role_count,
            "roles": role_names,
        }

    logger.info(
        "Preprocessor completed: %d principals processed (snapshot_date=%s).",
        len(result),
        snapshot_date.isoformat(),
    )

    return result
