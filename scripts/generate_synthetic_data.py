#!/usr/bin/env python
"""Deterministic synthetic Azure AD tenant snapshot generator.

Produces a JSON file that mirrors the structure of a real Azure AD role-assignment
export as defined in ``app/schemas/dataset_schema.py``.  The output is used for
integration tests, local development, and the public demo.

Design constraints
------------------
* **Deterministic output** — Faker and the ``random`` module are seeded with a
  fixed value (``SEED = 42``) so that the same JSON is produced on every run.
  Tests can assert specific findings against named accounts.
* **Ground-truth personas** — Before generating bulk random accounts, a set of
  hard-coded personas is injected that guarantees the expected finding categories:

  Overprivileged accounts (4):
    - Marcus Webb      — Global Admin whose only sign-ins are to Teams/Office
    - Diana Okafor     — Privileged Role Administrator who signs in via mobile
                         apps only, never Azure management tooling
    - Ryan Kowalski    — Helpdesk Admin + Security Admin + User Admin stacked
                         on a junior support account with minimal activity
    - svc-reporting    — ServicePrincipal with Global Admin, last sign-in >45d

  Dormant privileged accounts (4):
    - Trevor Blanchard — Global Admin, no sign-in in 65 days
    - Priya Subramaniam — Privileged Role Administrator, no sign-in in 55 days
    - svc-legacy-sync  — ServicePrincipal with User Administrator, no activity
                         in 90 days
    - Chen Wei         — Exchange Administrator + Security Administrator,
                         no sign-in in 40 days

  Correctly provisioned accounts (several):
    - Alice Johnson    — Global Admin with regular Azure management sign-ins
    - Bob Martinez     — Security Reader with recent activity (low-tier role)
    - Carol Nguyen     — User Administrator with recent regular sign-ins
    - svc-monitoring   — ServicePrincipal with Security Reader only, active

* **Approximately 100 users total** — bulk random accounts fill in the rest,
  weighted toward standard/low-privilege roles with realistic activity patterns.
* **Real Azure AD role GUIDs** — role definition IDs match actual built-in roles
  so the data is meaningful to engineers familiar with Entra ID.

Usage
-----
    python scripts/generate_synthetic_data.py
    # Writes: scripts/sample_dataset.json  (default)

    python scripts/generate_synthetic_data.py --output data/custom.json
    # Writes to the specified path instead.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from faker import Faker

# ---------------------------------------------------------------------------
# Seed for reproducibility
# ---------------------------------------------------------------------------

SEED = 42
random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# ---------------------------------------------------------------------------
# Snapshot anchor — all relative timestamps are computed from this point
# ---------------------------------------------------------------------------

# Fix the snapshot date so generated timestamps are stable across runs.
SNAPSHOT_DATE = datetime(2024, 11, 15, 12, 0, 0, tzinfo=UTC)
OBSERVATION_WINDOW_DAYS = 90


def _ts(dt: datetime) -> str:
    """Format a datetime as an ISO 8601 UTC string with Z suffix."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _days_ago(n: int, jitter_minutes: int = 0) -> datetime:
    """Return SNAPSHOT_DATE minus *n* days, with optional minute-level jitter."""
    base = SNAPSHOT_DATE - timedelta(days=n)
    if jitter_minutes:
        base += timedelta(minutes=random.randint(-jitter_minutes, jitter_minutes))
    return base


def _uid() -> str:
    """Return a new deterministic UUID string."""
    return str(uuid.UUID(int=random.getrandbits(128), version=4))


# ---------------------------------------------------------------------------
# Azure AD built-in role catalogue
# Real role definition IDs — stable across tenants for built-in roles.
# ---------------------------------------------------------------------------

ROLES: list[dict] = [
    # Tier 0
    {
        "id": "62e90394-69f5-4237-9190-012177145e10",
        "name": "Global Administrator",
        "tier": 0,
    },
    {
        "id": "fe930be7-5e62-47db-91af-98c3a49a38b1",
        "name": "Privileged Role Administrator",
        "tier": 0,
    },
    {
        "id": "7be44c8a-adaf-4e2a-84d6-ab2649e08a13",
        "name": "Privileged Authentication Administrator",
        "tier": 0,
    },
    # Tier 1
    {
        "id": "fe930be7-5e62-47db-91af-98c3a49a38b2",
        "name": "User Administrator",
        "tier": 1,
    },
    {
        "id": "194ae4cb-b126-40b2-bd5b-6091b380977d",
        "name": "Security Administrator",
        "tier": 1,
    },
    {
        "id": "29232cdf-9323-42fd-ade2-1d097af3e4de",
        "name": "Exchange Administrator",
        "tier": 1,
    },
    {
        "id": "f28a1f50-f6e7-4571-818b-6a12f2af6b6c",
        "name": "SharePoint Administrator",
        "tier": 1,
    },
    {
        "id": "17315797-102d-40b4-93e0-432062caca18",
        "name": "Compliance Administrator",
        "tier": 1,
    },
    {
        "id": "729827e3-9c14-49f7-bb1b-9608f156bbb8",
        "name": "Helpdesk Administrator",
        "tier": 1,
    },
    {
        "id": "9b895d92-2cd3-44c7-9d02-a6ac2d5ea5c3",
        "name": "Application Administrator",
        "tier": 1,
    },
    {
        "id": "158c047a-c907-4556-b7ef-446551a6b5f7",
        "name": "Cloud Application Administrator",
        "tier": 1,
    },
    # Tier 2
    {
        "id": "88d8e3e3-8f55-4a1e-953a-9b9898b8876b",
        "name": "Directory Readers",
        "tier": 2,
    },
    {
        "id": "5d6b6bb7-de71-4623-b4af-96380a352509",
        "name": "Security Reader",
        "tier": 2,
    },
    {"id": "4a5d8f65-41da-4de4-8968-e035b65339cf", "name": "Reports Reader", "tier": 2},
    {
        "id": "790c1fb9-7f7d-4f88-86a1-ef1f95c05c1b",
        "name": "Message Center Reader",
        "tier": 2,
    },
]

ROLE_BY_NAME: dict[str, dict] = {r["name"]: r for r in ROLES}
ROLE_BY_ID: dict[str, dict] = {r["id"]: r for r in ROLES}

# Roles available for random assignment to bulk users.
# Weighted: most bulk users get low-privilege roles.
BULK_ROLE_POOL: list[dict] = [
    ROLE_BY_NAME["Security Reader"],
    ROLE_BY_NAME["Directory Readers"],
    ROLE_BY_NAME["Reports Reader"],
    ROLE_BY_NAME["Message Center Reader"],
    ROLE_BY_NAME["Helpdesk Administrator"],
    ROLE_BY_NAME["User Administrator"],
]

BULK_ROLE_WEIGHTS = [30, 20, 15, 10, 15, 10]

# Common apps seen in Azure AD sign-in logs.
APPS = [
    "Microsoft Teams",
    "Microsoft Office",
    "Office 365 Exchange Online",
    "Windows Sign In",
    "Microsoft MyApps",
    "Azure Active Directory PowerShell",
    "Microsoft Graph",
    "Microsoft Azure Management",
]

NON_ADMIN_APPS = [
    "Microsoft Teams",
    "Microsoft Office",
    "Office 365 Exchange Online",
    "Windows Sign In",
    "Microsoft MyApps",
]

ADMIN_APPS = [
    "Microsoft Azure Management",
    "Azure Active Directory PowerShell",
    "Microsoft Graph",
]


# ---------------------------------------------------------------------------
# Sign-in log helpers
# ---------------------------------------------------------------------------


def _make_sign_in(
    log_id: str,
    user_id: str,
    display_name: str,
    days_ago_value: int,
    app: str,
    status: str = "Success",
) -> dict:
    """Build a single sign-in log entry."""
    ts = _days_ago(days_ago_value, jitter_minutes=120)
    return {
        "id": log_id,
        "userId": user_id,
        "userDisplayName": display_name,
        "signInTimestamp": _ts(ts),
        "appDisplayName": app,
        "status": status,
        "ipAddress": fake.ipv4_public(),
    }


def _workday_sign_ins(
    user_id: str,
    display_name: str,
    start_counter: int,
    days_range: tuple[int, int],
    app_pool: list[str],
    count: int = 12,
) -> tuple[list[dict], int]:
    """Generate *count* weekday-clustered sign-in entries over *days_range*.

    Returns the list of log entries and the updated counter.
    """
    entries: list[dict] = []
    used_days: set[int] = set()
    counter = start_counter
    attempts = 0
    while len(entries) < count and attempts < count * 5:
        attempts += 1
        day = random.randint(*days_range)
        # Approximate weekday check: day offset from snapshot.
        candidate = SNAPSHOT_DATE - timedelta(days=day)
        if candidate.weekday() >= 5:  # Saturday=5, Sunday=6
            continue
        if day in used_days:
            continue
        used_days.add(day)
        app = random.choice(app_pool)
        entries.append(
            _make_sign_in(
                f"sl-{counter:06d}",
                user_id,
                display_name,
                day,
                app,
            )
        )
        counter += 1
    return entries, counter


# ---------------------------------------------------------------------------
# Role assignment helper
# ---------------------------------------------------------------------------


def _make_ra(
    ra_id: str,
    principal_id: str,
    role: dict,
    assignment_type: str = "direct",
    assigned_via: str | None = None,
    assigned_at_days_ago: int = 400,
) -> dict:
    """Build a single role assignment entry."""
    return {
        "id": ra_id,
        "principalId": principal_id,
        "roleDefinitionId": role["id"],
        "roleName": role["name"],
        "assignmentType": assignment_type,
        "assignedVia": assigned_via,
        "assignedAt": _ts(_days_ago(assigned_at_days_ago)),
    }


# ---------------------------------------------------------------------------
# Ground-truth persona definitions
# ---------------------------------------------------------------------------
# Each persona is a dict carrying enough fields to build the user, role
# assignments, and sign-in logs.  These are processed first so their IDs are
# stable across generator runs.


def _build_ground_truth_accounts(
    sign_in_counter: int,
    ra_counter: int,
) -> tuple[
    list[dict],  # users
    list[dict],  # role_assignments
    list[dict],  # sign_in_logs
    int,  # updated sign_in_counter
    int,  # updated ra_counter
]:
    """Construct the hard-coded personas that underpin audit test assertions.

    Returns populated lists for users, role_assignments, and sign_in_logs
    plus the updated running counters.
    """
    users: list[dict] = []
    role_assignments: list[dict] = []
    sign_in_logs: list[dict] = []

    sc = sign_in_counter  # sign-in log counter
    rc = ra_counter  # role assignment counter

    # -----------------------------------------------------------------------
    # OVERPRIVILEGED ACCOUNTS
    # -----------------------------------------------------------------------
    # OP-1: Marcus Webb — Global Admin, only signs in to non-admin apps
    # Justification: holds the most powerful role but zero Azure management
    # activity; all sign-ins are consumer-grade (Teams, Office).
    # -----------------------------------------------------------------------
    marcus_id = "op-user-0001-marcus-webb-000000000001"
    users.append(
        {
            "id": marcus_id,
            "displayName": "Marcus Webb",
            "userPrincipalName": "marcus.webb@contoso.onmicrosoft.com",
            "userType": "Member",
            "accountEnabled": True,
        }
    )
    role_assignments.append(
        _make_ra(
            f"ra-{rc:06d}",
            marcus_id,
            ROLE_BY_NAME["Global Administrator"],
            assigned_at_days_ago=550,
        )
    )
    rc += 1
    # Sign-ins only to non-admin apps, recent enough to avoid dormancy flag.
    for day, app in [
        (3, "Microsoft Teams"),
        (5, "Microsoft Office"),
        (8, "Microsoft Office"),
        (12, "Office 365 Exchange Online"),
        (15, "Microsoft Teams"),
        (20, "Microsoft Office"),
    ]:
        sign_in_logs.append(_make_sign_in(f"sl-{sc:06d}", marcus_id, "Marcus Webb", day, app))
        sc += 1

    # -----------------------------------------------------------------------
    # OP-2: Diana Okafor — Privileged Role Administrator, mobile-only sign-ins
    # Justification: Tier 0 role, active account, but usage pattern (mobile,
    # consumer apps) is inconsistent with privileged administration duties.
    # -----------------------------------------------------------------------
    diana_id = "op-user-0002-diana-okafor-000000000002"
    users.append(
        {
            "id": diana_id,
            "displayName": "Diana Okafor",
            "userPrincipalName": "diana.okafor@contoso.onmicrosoft.com",
            "userType": "Member",
            "accountEnabled": True,
        }
    )
    role_assignments.append(
        _make_ra(
            f"ra-{rc:06d}",
            diana_id,
            ROLE_BY_NAME["Privileged Role Administrator"],
            assigned_at_days_ago=480,
        )
    )
    rc += 1
    for day, app in [
        (2, "Microsoft Teams"),
        (4, "Microsoft Office"),
        (7, "Office 365 Exchange Online"),
        (11, "Microsoft Teams"),
        (16, "Microsoft Office"),
    ]:
        sign_in_logs.append(_make_sign_in(f"sl-{sc:06d}", diana_id, "Diana Okafor", day, app))
        sc += 1

    # -----------------------------------------------------------------------
    # OP-3: Ryan Kowalski — role accumulation (Helpdesk + Security Admin +
    # User Admin) on what should be a limited support account.
    # Justification: three privileged roles on a junior-pattern account;
    # sign-in activity is present but through helpdesk tooling only.
    # -----------------------------------------------------------------------
    ryan_id = "op-user-0003-ryan-kowalski-000000000003"
    users.append(
        {
            "id": ryan_id,
            "displayName": "Ryan Kowalski",
            "userPrincipalName": "ryan.kowalski@contoso.onmicrosoft.com",
            "userType": "Member",
            "accountEnabled": True,
        }
    )
    for role_name, age in [
        ("Helpdesk Administrator", 600),
        ("Security Administrator", 400),
        ("User Administrator", 200),
    ]:
        role_assignments.append(
            _make_ra(
                f"ra-{rc:06d}",
                ryan_id,
                ROLE_BY_NAME[role_name],
                assigned_at_days_ago=age,
            )
        )
        rc += 1
    for day, app in [
        (1, "Microsoft Teams"),
        (3, "Office 365 Exchange Online"),
        (6, "Microsoft Office"),
        (9, "Microsoft Teams"),
        (14, "Office 365 Exchange Online"),
    ]:
        sign_in_logs.append(_make_sign_in(f"sl-{sc:06d}", ryan_id, "Ryan Kowalski", day, app))
        sc += 1

    # -----------------------------------------------------------------------
    # OP-4: svc-reporting — ServicePrincipal with Global Admin, last active 47d
    # Justification: service account holding tenant's highest privilege with
    # a sign-in pattern that predates last activity by 47 days — not quite
    # dormant by the default threshold but clearly overprivileged for a
    # reporting service.
    # -----------------------------------------------------------------------
    svc_reporting_id = "op-user-0004-svc-reporting-0000000000004"
    users.append(
        {
            "id": svc_reporting_id,
            "displayName": "svc-reporting",
            "userPrincipalName": "svc-reporting@contoso.onmicrosoft.com",
            "userType": "ServicePrincipal",
            "accountEnabled": True,
        }
    )
    role_assignments.append(
        _make_ra(
            f"ra-{rc:06d}",
            svc_reporting_id,
            ROLE_BY_NAME["Global Administrator"],
            assigned_at_days_ago=700,
        )
    )
    rc += 1
    # Last sign-in was 47 days ago — within 30-day dormancy window but only
    # just; the overprivileged signal comes from role tier vs account type.
    for day, app in [
        (47, "Microsoft Graph"),
        (62, "Microsoft Graph"),
        (75, "Microsoft Graph"),
    ]:
        sign_in_logs.append(
            _make_sign_in(f"sl-{sc:06d}", svc_reporting_id, "svc-reporting", day, app)
        )
        sc += 1

    # -----------------------------------------------------------------------
    # DORMANT PRIVILEGED ACCOUNTS
    # -----------------------------------------------------------------------
    # DP-1: Trevor Blanchard — Global Admin, last sign-in 65 days ago
    # Clear dormancy: Tier 0 role, 65-day gap exceeds the 30-day threshold.
    # -----------------------------------------------------------------------
    trevor_id = "dp-user-0001-trevor-blanchard-000000001"
    users.append(
        {
            "id": trevor_id,
            "displayName": "Trevor Blanchard",
            "userPrincipalName": "trevor.blanchard@contoso.onmicrosoft.com",
            "userType": "Member",
            "accountEnabled": True,
        }
    )
    role_assignments.append(
        _make_ra(
            f"ra-{rc:06d}",
            trevor_id,
            ROLE_BY_NAME["Global Administrator"],
            assigned_at_days_ago=730,
        )
    )
    rc += 1
    # Deliberately sparse sign-ins — all older than 30 days.
    for day, app in [
        (65, "Microsoft Azure Management"),
        (72, "Microsoft Teams"),
        (80, "Microsoft Azure Management"),
    ]:
        sign_in_logs.append(_make_sign_in(f"sl-{sc:06d}", trevor_id, "Trevor Blanchard", day, app))
        sc += 1

    # -----------------------------------------------------------------------
    # DP-2: Priya Subramaniam — Privileged Role Administrator, 55 days dormant
    # Clear dormancy: Tier 0, no sign-in for 55 days.
    # -----------------------------------------------------------------------
    priya_id = "dp-user-0002-priya-subramaniam-0000000002"
    users.append(
        {
            "id": priya_id,
            "displayName": "Priya Subramaniam",
            "userPrincipalName": "priya.subramaniam@contoso.onmicrosoft.com",
            "userType": "Member",
            "accountEnabled": True,
        }
    )
    role_assignments.append(
        _make_ra(
            f"ra-{rc:06d}",
            priya_id,
            ROLE_BY_NAME["Privileged Role Administrator"],
            assigned_at_days_ago=620,
        )
    )
    rc += 1
    for day, app in [
        (55, "Azure Active Directory PowerShell"),
        (61, "Microsoft Azure Management"),
        (68, "Azure Active Directory PowerShell"),
    ]:
        sign_in_logs.append(_make_sign_in(f"sl-{sc:06d}", priya_id, "Priya Subramaniam", day, app))
        sc += 1

    # -----------------------------------------------------------------------
    # DP-3: svc-legacy-sync — ServicePrincipal, User Administrator, 90d silent
    # No sign-in entries at all within the observation window.  Standing
    # Tier 1 privilege on a service account that has been silent for the
    # entire 90-day window.
    # -----------------------------------------------------------------------
    svc_legacy_id = "dp-user-0003-svc-legacy-sync-000000000003"
    users.append(
        {
            "id": svc_legacy_id,
            "displayName": "svc-legacy-sync",
            "userPrincipalName": "svc-legacy-sync@contoso.onmicrosoft.com",
            "userType": "ServicePrincipal",
            "accountEnabled": True,
        }
    )
    role_assignments.append(
        _make_ra(
            f"ra-{rc:06d}",
            svc_legacy_id,
            ROLE_BY_NAME["User Administrator"],
            assigned_at_days_ago=900,
        )
    )
    rc += 1
    # Intentionally zero sign-in entries for this account.

    # -----------------------------------------------------------------------
    # DP-4: Chen Wei — Exchange Admin + Security Admin, 40 days dormant
    # Tier 1 roles on an account that has been idle for 40 days.
    # -----------------------------------------------------------------------
    chen_id = "dp-user-0004-chen-wei-00000000000000000004"
    users.append(
        {
            "id": chen_id,
            "displayName": "Chen Wei",
            "userPrincipalName": "chen.wei@contoso.onmicrosoft.com",
            "userType": "Member",
            "accountEnabled": True,
        }
    )
    for role_name, age in [
        ("Exchange Administrator", 500),
        ("Security Administrator", 380),
    ]:
        role_assignments.append(
            _make_ra(
                f"ra-{rc:06d}",
                chen_id,
                ROLE_BY_NAME[role_name],
                assigned_at_days_ago=age,
            )
        )
        rc += 1
    for day, app in [
        (40, "Office 365 Exchange Online"),
        (45, "Microsoft Azure Management"),
        (52, "Office 365 Exchange Online"),
    ]:
        sign_in_logs.append(_make_sign_in(f"sl-{sc:06d}", chen_id, "Chen Wei", day, app))
        sc += 1

    # -----------------------------------------------------------------------
    # CORRECTLY PROVISIONED ACCOUNTS (must NOT be flagged)
    # -----------------------------------------------------------------------
    # CP-1: Alice Johnson — Global Admin with regular Azure management activity
    # Appropriate: frequent, recent sign-ins to Azure management tooling
    # demonstrate active use of the role.
    # -----------------------------------------------------------------------
    alice_id = "cp-user-0001-alice-johnson-00000000000001"
    users.append(
        {
            "id": alice_id,
            "displayName": "Alice Johnson",
            "userPrincipalName": "alice.johnson@contoso.onmicrosoft.com",
            "userType": "Member",
            "accountEnabled": True,
        }
    )
    role_assignments.append(
        _make_ra(
            f"ra-{rc:06d}",
            alice_id,
            ROLE_BY_NAME["Global Administrator"],
            assigned_at_days_ago=900,
        )
    )
    rc += 1
    logs, sc = _workday_sign_ins(alice_id, "Alice Johnson", sc, (1, 30), ADMIN_APPS, count=10)
    sign_in_logs.extend(logs)

    # -----------------------------------------------------------------------
    # CP-2: Bob Martinez — Security Reader, recent activity
    # Appropriate: low-tier role, active user, no overprivilege concern.
    # -----------------------------------------------------------------------
    bob_id = "cp-user-0002-bob-martinez-000000000000002"
    users.append(
        {
            "id": bob_id,
            "displayName": "Bob Martinez",
            "userPrincipalName": "bob.martinez@contoso.onmicrosoft.com",
            "userType": "Member",
            "accountEnabled": True,
        }
    )
    role_assignments.append(
        _make_ra(
            f"ra-{rc:06d}",
            bob_id,
            ROLE_BY_NAME["Security Reader"],
            assigned_at_days_ago=200,
        )
    )
    rc += 1
    logs, sc = _workday_sign_ins(bob_id, "Bob Martinez", sc, (1, 20), NON_ADMIN_APPS, count=8)
    sign_in_logs.extend(logs)

    # -----------------------------------------------------------------------
    # CP-3: Carol Nguyen — User Administrator with regular sign-ins
    # Appropriate: single Tier 1 role, active and recent usage.
    # -----------------------------------------------------------------------
    carol_id = "cp-user-0003-carol-nguyen-000000000000003"
    users.append(
        {
            "id": carol_id,
            "displayName": "Carol Nguyen",
            "userPrincipalName": "carol.nguyen@contoso.onmicrosoft.com",
            "userType": "Member",
            "accountEnabled": True,
        }
    )
    role_assignments.append(
        _make_ra(
            f"ra-{rc:06d}",
            carol_id,
            ROLE_BY_NAME["User Administrator"],
            assigned_at_days_ago=300,
        )
    )
    rc += 1
    logs, sc = _workday_sign_ins(
        carol_id,
        "Carol Nguyen",
        sc,
        (1, 25),
        NON_ADMIN_APPS + ["Azure Active Directory PowerShell"],
        count=10,
    )
    sign_in_logs.extend(logs)

    # -----------------------------------------------------------------------
    # CP-4: svc-monitoring — ServicePrincipal with Security Reader only
    # Appropriate: read-only role, service account, regular Graph API access.
    # -----------------------------------------------------------------------
    svc_monitoring_id = "cp-user-0004-svc-monitoring-000000000004"
    users.append(
        {
            "id": svc_monitoring_id,
            "displayName": "svc-monitoring",
            "userPrincipalName": "svc-monitoring@contoso.onmicrosoft.com",
            "userType": "ServicePrincipal",
            "accountEnabled": True,
        }
    )
    role_assignments.append(
        _make_ra(
            f"ra-{rc:06d}",
            svc_monitoring_id,
            ROLE_BY_NAME["Security Reader"],
            assigned_at_days_ago=450,
        )
    )
    rc += 1
    # Service accounts sign in via Graph API consistently.
    for day in range(1, 30, 3):
        sign_in_logs.append(
            _make_sign_in(
                f"sl-{sc:06d}",
                svc_monitoring_id,
                "svc-monitoring",
                day,
                "Microsoft Graph",
            )
        )
        sc += 1

    return users, role_assignments, sign_in_logs, sc, rc


# ---------------------------------------------------------------------------
# Groups with inherited role assignments
# ---------------------------------------------------------------------------


def _build_groups(
    all_user_ids: list[str],
    ground_truth_user_ids: set[str],
    ra_counter: int,
) -> tuple[list[dict], list[dict], int]:
    """Create groups, assign roles to them, and build group-inherited RAs.

    Returns the groups list, additional role_assignments for group-inherited
    memberships, and the updated ra_counter.
    """
    groups: list[dict] = []
    extra_role_assignments: list[dict] = []
    rc = ra_counter

    # Only pick bulk users (non-ground-truth) for group membership to keep
    # the ground-truth accounts cleanly associated with their direct
    # assignments and avoid test interference.
    bulk_ids = [uid for uid in all_user_ids if uid not in ground_truth_user_ids]

    if len(bulk_ids) < 6:
        return groups, extra_role_assignments, rc

    # ------------------------------------------------------------------
    # Group 1: Tier0-Admins-PIM — role-assignable, Privileged Role Admin
    # Members inherit Privileged Role Administrator via group.
    # ------------------------------------------------------------------
    tier0_members = random.sample(bulk_ids, min(3, len(bulk_ids)))
    tier0_group_id = "grp-0001-tier0-admins-pim-00000000000001"
    groups.append(
        {
            "id": tier0_group_id,
            "displayName": "Tier0-Admins (PIM)",
            "isRoleAssignable": True,
            "members": tier0_members,
            "assignedRoles": [ROLE_BY_NAME["Privileged Role Administrator"]["id"]],
        }
    )
    for member_id in tier0_members:
        extra_role_assignments.append(
            _make_ra(
                f"ra-{rc:06d}",
                member_id,
                ROLE_BY_NAME["Privileged Role Administrator"],
                assignment_type="group",
                assigned_via="Tier0-Admins (PIM)",
                assigned_at_days_ago=random.randint(200, 800),
            )
        )
        rc += 1

    # ------------------------------------------------------------------
    # Group 2: Security Operations — role-assignable, Security Administrator
    # ------------------------------------------------------------------
    remaining = [uid for uid in bulk_ids if uid not in tier0_members]
    secops_members = random.sample(remaining, min(4, len(remaining)))
    secops_group_id = "grp-0002-security-operations-000000000002"
    groups.append(
        {
            "id": secops_group_id,
            "displayName": "Security Operations",
            "isRoleAssignable": True,
            "members": secops_members,
            "assignedRoles": [ROLE_BY_NAME["Security Administrator"]["id"]],
        }
    )
    for member_id in secops_members:
        extra_role_assignments.append(
            _make_ra(
                f"ra-{rc:06d}",
                member_id,
                ROLE_BY_NAME["Security Administrator"],
                assignment_type="group",
                assigned_via="Security Operations",
                assigned_at_days_ago=random.randint(100, 500),
            )
        )
        rc += 1

    # ------------------------------------------------------------------
    # Group 3: Helpdesk-L1 — standard security group, Helpdesk Administrator
    # ------------------------------------------------------------------
    remaining2 = [uid for uid in remaining if uid not in secops_members]
    helpdesk_members = random.sample(remaining2, min(5, len(remaining2)))
    helpdesk_group_id = "grp-0003-helpdesk-l1-0000000000000003"
    groups.append(
        {
            "id": helpdesk_group_id,
            "displayName": "Helpdesk-L1",
            "isRoleAssignable": True,
            "members": helpdesk_members,
            "assignedRoles": [ROLE_BY_NAME["Helpdesk Administrator"]["id"]],
        }
    )
    for member_id in helpdesk_members:
        extra_role_assignments.append(
            _make_ra(
                f"ra-{rc:06d}",
                member_id,
                ROLE_BY_NAME["Helpdesk Administrator"],
                assignment_type="group",
                assigned_via="Helpdesk-L1",
                assigned_at_days_ago=random.randint(60, 400),
            )
        )
        rc += 1

    # ------------------------------------------------------------------
    # Group 4: All-Staff — plain security group, no privileged roles
    # All bulk users are members; no role assignments on the group itself.
    # ------------------------------------------------------------------
    groups.append(
        {
            "id": "grp-0004-all-staff-0000000000000000004",
            "displayName": "All Staff",
            "isRoleAssignable": False,
            "members": bulk_ids[:],
            "assignedRoles": [],
        }
    )

    return groups, extra_role_assignments, rc


# ---------------------------------------------------------------------------
# Bulk user generation
# ---------------------------------------------------------------------------


def _build_bulk_users(
    count: int,
    sign_in_counter: int,
    ra_counter: int,
) -> tuple[list[dict], list[dict], list[dict], int, int]:
    """Generate *count* generic users with randomised roles and sign-in patterns.

    Approximately 10 % of bulk users have zero sign-in activity to ensure
    the population includes borderline dormancy cases for low-privilege roles
    (which should generally NOT trigger findings).
    """
    users: list[dict] = []
    role_assignments: list[dict] = []
    sign_in_logs: list[dict] = []
    sc = sign_in_counter
    rc = ra_counter

    departments = [
        "Engineering",
        "Finance",
        "HR",
        "Legal",
        "Marketing",
        "Operations",
        "Product",
        "Sales",
        "Support",
        "IT",
    ]

    for i in range(count):
        uid = _uid()
        first = fake.first_name()
        last = fake.last_name()
        display_name = f"{first} {last}"
        dept = random.choice(departments)
        upn = f"{first.lower()}.{last.lower()}@contoso.onmicrosoft.com"

        user_type: str
        if i % 20 == 0:
            user_type = "ServicePrincipal"
            display_name = f"svc-{dept.lower()}-{fake.word()}"
            upn = f"{display_name}@contoso.onmicrosoft.com"
        elif i % 15 == 0:
            user_type = "Guest"
            upn = (
                f"{first.lower()}.{last.lower()}_external@partner.com#EXT#@contoso.onmicrosoft.com"
            )
        else:
            user_type = "Member"

        users.append(
            {
                "id": uid,
                "displayName": display_name,
                "userPrincipalName": upn,
                "userType": user_type,
                "accountEnabled": True,
            }
        )

        # Assign a single role from the bulk pool.
        role = random.choices(BULK_ROLE_POOL, weights=BULK_ROLE_WEIGHTS, k=1)[0]
        assignment_age = random.randint(30, 700)
        role_assignments.append(
            _make_ra(
                f"ra-{rc:06d}",
                uid,
                role,
                assigned_at_days_ago=assignment_age,
            )
        )
        rc += 1

        # ~10 % of bulk users have no sign-in logs.
        if random.random() < 0.10:
            continue

        # Random sign-in distribution across the 90-day window.
        sign_in_count = random.randint(3, 20)
        app_pool = NON_ADMIN_APPS if user_type != "ServicePrincipal" else ["Microsoft Graph"]
        logs, sc = _workday_sign_ins(
            uid,
            display_name,
            sc,
            (1, OBSERVATION_WINDOW_DAYS - 1),
            app_pool,
            count=sign_in_count,
        )
        sign_in_logs.extend(logs)

    return users, role_assignments, sign_in_logs, sc, rc


# ---------------------------------------------------------------------------
# Ground-truth manifest
# ---------------------------------------------------------------------------


def _build_ground_truth_manifest() -> dict:
    """Return the expected audit findings keyed by principal display name.

    This manifest is embedded in the output JSON under ``_groundTruthManifest``
    so that integration tests can load it alongside the dataset and assert
    specific findings without hard-coding principal IDs in test source code.
    """
    return {
        "description": (
            "Expected audit findings for the synthetic dataset. "
            "Integration tests MUST assert that at minimum these principals "
            "appear in the audit output with the listed category and severity."
        ),
        "expectedFindings": [
            # Overprivileged
            {
                "displayName": "Marcus Webb",
                "category": "overprivileged",
                "minSeverity": "high",
                "reason": "Global Administrator with zero Azure management sign-in activity",
            },
            {
                "displayName": "Diana Okafor",
                "category": "overprivileged",
                "minSeverity": "high",
                "reason": "Privileged Role Administrator with consumer-app-only sign-in pattern",
            },
            {
                "displayName": "Ryan Kowalski",
                "category": "overprivileged",
                "minSeverity": "high",
                "reason": "Three privileged roles (Helpdesk Admin + Security Admin + User Admin) on a single account",
            },
            {
                "displayName": "svc-reporting",
                "category": "overprivileged",
                "minSeverity": "high",
                "reason": "ServicePrincipal holding Global Administrator with infrequent Graph API sign-ins",
            },
            # Dormant privileged
            {
                "displayName": "Trevor Blanchard",
                "category": "dormant_privileged",
                "minSeverity": "critical",
                "reason": "Global Administrator, last sign-in 65 days ago (exceeds 30-day threshold)",
            },
            {
                "displayName": "Priya Subramaniam",
                "category": "dormant_privileged",
                "minSeverity": "critical",
                "reason": "Privileged Role Administrator, last sign-in 55 days ago",
            },
            {
                "displayName": "svc-legacy-sync",
                "category": "dormant_privileged",
                "minSeverity": "high",
                "reason": "ServicePrincipal with User Administrator, zero sign-in activity in observation window",
            },
            {
                "displayName": "Chen Wei",
                "category": "dormant_privileged",
                "minSeverity": "high",
                "reason": "Exchange Administrator + Security Administrator, last sign-in 40 days ago",
            },
        ],
        "shouldNotBeFlaged": [
            {
                "displayName": "Alice Johnson",
                "reason": "Global Admin with frequent, recent Azure management sign-ins",
            },
            {
                "displayName": "Bob Martinez",
                "reason": "Security Reader (Tier 2), active user, no overprivilege concern",
            },
            {
                "displayName": "Carol Nguyen",
                "reason": "User Administrator with regular recent activity",
            },
            {
                "displayName": "svc-monitoring",
                "reason": "ServicePrincipal with Security Reader only, consistent Graph API access",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Top-level assembly
# ---------------------------------------------------------------------------


def generate_dataset(bulk_user_count: int = 88) -> dict:
    """Assemble and return the complete synthetic dataset.

    Parameters
    ----------
    bulk_user_count:
        Number of randomly generated users to add in addition to the
        hard-coded ground-truth personas (12 total personas = 4 OP + 4 DP
        + 4 CP).  Default produces approximately 100 users total.

    Returns
    -------
    dict
        A dataset conforming to ``AzureADDatasetPayload`` plus a
        ``_groundTruthManifest`` key with expected audit findings.
    """
    # Re-seed on every call so that multiple calls within the same process
    # produce identical output.
    random.seed(SEED)
    Faker.seed(SEED)

    sign_in_counter = 1
    ra_counter = 1

    # Step 1: build ground-truth personas.
    (
        gt_users,
        gt_role_assignments,
        gt_sign_ins,
        sign_in_counter,
        ra_counter,
    ) = _build_ground_truth_accounts(sign_in_counter, ra_counter)

    # Step 2: build bulk random users.
    (
        bulk_users,
        bulk_role_assignments,
        bulk_sign_ins,
        sign_in_counter,
        ra_counter,
    ) = _build_bulk_users(bulk_user_count, sign_in_counter, ra_counter)

    all_users = gt_users + bulk_users
    all_user_ids = [u["id"] for u in all_users]
    gt_user_ids = {u["id"] for u in gt_users}

    # Step 3: build groups with group-inherited role assignments.
    groups, group_role_assignments, ra_counter = _build_groups(
        all_user_ids, gt_user_ids, ra_counter
    )

    all_role_assignments = gt_role_assignments + bulk_role_assignments + group_role_assignments
    all_sign_ins = gt_sign_ins + bulk_sign_ins

    return {
        "users": all_users,
        "roleAssignments": all_role_assignments,
        "signInLogs": all_sign_ins,
        "groups": groups,
        "_groundTruthManifest": _build_ground_truth_manifest(),
        "_meta": {
            "generatedAt": _ts(SNAPSHOT_DATE),
            "snapshotDate": _ts(SNAPSHOT_DATE),
            "observationWindowDays": OBSERVATION_WINDOW_DAYS,
            "seed": SEED,
            "totalUsers": len(all_users),
            "totalRoleAssignments": len(all_role_assignments),
            "totalSignInLogs": len(all_sign_ins),
            "totalGroups": len(groups),
        },
    }


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point — generate the dataset and write it to disk."""
    parser = argparse.ArgumentParser(
        description="Generate a deterministic synthetic Azure AD role-assignment dataset."
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).parent / "sample_dataset.json"),
        help="Path to write the output JSON (default: scripts/sample_dataset.json).",
    )
    parser.add_argument(
        "--bulk-users",
        type=int,
        default=88,
        help="Number of randomly generated users in addition to the 12 ground-truth personas.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        default=True,
        help="Write indented JSON (default: True).",
    )
    args = parser.parse_args()

    print(
        f"Generating synthetic dataset (seed={SEED}, bulk_users={args.bulk_users}) ...",
        file=sys.stderr,
    )

    dataset = generate_dataset(bulk_user_count=args.bulk_users)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    indent = 2 if args.pretty else None
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(dataset, fh, indent=indent, ensure_ascii=False)

    meta = dataset["_meta"]
    print(
        f"Dataset written to {output_path}\n"
        f"  Users:            {meta['totalUsers']}\n"
        f"  Role assignments: {meta['totalRoleAssignments']}\n"
        f"  Sign-in logs:     {meta['totalSignInLogs']}\n"
        f"  Groups:           {meta['totalGroups']}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
