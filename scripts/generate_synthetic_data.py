#!/usr/bin/env python3
"""Deterministic synthetic Azure AD tenant snapshot generator.

Produces a JSON file that conforms to the ``AzureADDatasetPayload`` schema
defined in ``app/schemas/dataset_schema.py``.  The output is suitable for
loading via ``POST /api/v1/datasets``, seeding the demo database, and
driving integration tests.

Design constraints
------------------
* **Deterministic** — a fixed Faker/random seed guarantees the same output
  on every run, making tests and demos reproducible.
* **Ground-truth manifest** — a companion ``ground_truth.json`` file is
  written alongside the dataset documenting which principals are expected
  to be flagged, their expected category, and the reason.  Integration
  tests import this file to assert correct pipeline behaviour.
* **Realistic feel** — display names are plausible, role names match real
  Azure AD built-in roles, sign-in timestamps cluster on weekdays during
  business hours, and IP addresses use the RFC 5737 documentation range.
* **Deliberate audit targets** — the generator hard-codes four overprivileged
  accounts and four dormant privileged accounts with unambiguous signal so
  that the detection pipeline has clear positive cases to identify.

Usage
-----
::

    python scripts/generate_synthetic_data.py
    python scripts/generate_synthetic_data.py --output data/my_dataset.json
    python scripts/generate_synthetic_data.py --seed 99 --output data/alt.json

Outputs
-------
``data/sample_dataset.json``
    The full tenant snapshot payload.

``data/ground_truth.json``
    A list of expected findings for integration test assertions.
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from faker import Faker

# ---------------------------------------------------------------------------
# Constants — Azure AD built-in roles (real definition IDs)
# ---------------------------------------------------------------------------

# Each tuple: (display_name, role_definition_id, tier)
# Tier 0 = global control; tier 1 = elevated; tier 2 = read-only/narrow
AZURE_AD_ROLES: list[tuple[str, str, int]] = [
    # Tier 0
    ("Global Administrator", "62e90394-69f5-4237-9190-012177145e10", 0),
    ("Privileged Role Administrator", "fe930be7-5e62-47db-91af-98c3a49a38b1", 0),
    (
        "Privileged Authentication Administrator",
        "7be44c8a-adaf-4e2a-84d6-ab2649e08a13",
        0,
    ),
    # Tier 1
    ("User Administrator", "d37c8bed-0711-4417-ba38-b4abe66ce4c2", 1),
    ("Security Administrator", "194ae4cb-b126-40b2-bd5b-6091b380977d", 1),
    ("Exchange Administrator", "29232cdf-9323-42fd-ade2-1d097af3e4de", 1),
    ("SharePoint Administrator", "f28a1f50-f6e7-4571-818b-6a12f2af6b6c", 1),
    ("Compliance Administrator", "17315797-102d-40b4-93e0-432062caca18", 1),
    ("Helpdesk Administrator", "729827e3-9c14-49f7-bb1b-9608f156bbb8", 1),
    ("Application Administrator", "9b895d92-2cd3-44c7-9d02-a6ac2d5ea5c3", 1),
    ("Cloud Application Administrator", "158c047a-c907-4556-b7ef-446551a6b5f7", 1),
    ("Authentication Administrator", "c4e39bd9-1100-46d3-8c65-fb160da0071f", 1),
    # Tier 2
    ("Directory Readers", "88d8e3e3-8f55-4a1e-953a-9b9898b8876b", 2),
    ("Security Reader", "5d6b6bb7-de71-4623-b4af-96380a352509", 2),
    ("Reports Reader", "4a5d8f65-41da-4de4-8968-e035b65339cf", 2),
]

# Role name → (definition_id, tier) lookup
ROLE_BY_NAME: dict[str, tuple[str, int]] = {
    name: (rid, tier) for name, rid, tier in AZURE_AD_ROLES
}

# Realistic applications that appear in Azure AD sign-in logs
APP_NAMES: list[str] = [
    "Microsoft Teams",
    "Microsoft Office",
    "Office 365 Exchange Online",
    "Microsoft Azure Management",
    "Windows Sign In",
    "Microsoft Graph",
    "Azure Active Directory PowerShell",
    "Microsoft 365 Admin Center",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ts(dt: datetime) -> str:
    """Return an ISO 8601 UTC string with Z suffix."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _random_business_datetime(
    rng: random.Random,
    start: datetime,
    end: datetime,
) -> datetime:
    """Return a random datetime between *start* and *end* weighted toward
    weekday business hours (08:00–18:00 UTC) to mimic realistic sign-in
    patterns.

    The function makes up to 20 attempts to land on a weekday; if all
    attempts produce a weekend it returns the last candidate anyway so
    the distribution never stalls.
    """
    delta_seconds = int((end - start).total_seconds())
    for _ in range(20):
        offset = timedelta(
            seconds=rng.randint(0, delta_seconds),
            hours=rng.randint(0, 10),  # skew toward daytime
        )
        candidate = start + offset
        # Monday=0, Friday=4
        if candidate.weekday() < 5:
            return candidate
    return start + timedelta(seconds=rng.randint(0, delta_seconds))


def _fake_ip(rng: random.Random) -> str:
    """Return an IP from the RFC 5737 documentation range (203.0.113.x)."""
    return f"203.0.113.{rng.randint(1, 254)}"


def _uuid(fake: Faker) -> str:
    """Return a lower-case UUID4 string."""
    return str(fake.uuid4())


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


def generate(
    seed: int = 42,
    snapshot_date: datetime | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Generate a synthetic Azure AD tenant snapshot and a ground-truth manifest.

    Parameters
    ----------
    seed:
        RNG seed for deterministic output.  Pass any integer; the default
        (42) is used for the committed sample dataset.
    snapshot_date:
        The point-in-time the snapshot represents.  Defaults to
        ``2025-01-15T00:00:00Z`` so that the committed sample is stable
        regardless of when the generator runs.

    Returns
    -------
    tuple[dict, list]
        ``(dataset_payload, ground_truth_findings)`` where
        ``dataset_payload`` conforms to ``AzureADDatasetPayload`` and
        ``ground_truth_findings`` is a list of dicts describing which
        principals are expected to trigger audit findings.
    """
    if snapshot_date is None:
        snapshot_date = datetime(2025, 1, 15, 0, 0, 0, tzinfo=UTC)

    fake = Faker()
    Faker.seed(seed)
    rng = random.Random(seed)

    observation_start = snapshot_date - timedelta(days=90)

    # ---------------------------------------------------------------
    # Role-name lookup helpers
    # ---------------------------------------------------------------
    def role(name: str) -> dict[str, str]:
        rid, _ = ROLE_BY_NAME[name]
        return {"name": name, "id": rid}

    # ---------------------------------------------------------------
    # 1. Users
    # ---------------------------------------------------------------
    # We build users in labelled categories so we can later assign
    # roles and sign-in patterns with full control over the "ground truth".

    users: list[dict[str, Any]] = []

    def _make_user(
        uid: str,
        display_name: str,
        upn: str,
        user_type: str,
        account_enabled: bool = True,
    ) -> dict[str, Any]:
        return {
            "id": uid,
            "displayName": display_name,
            "userPrincipalName": upn,
            "userType": user_type,
            "accountEnabled": account_enabled,
        }

    domain = "contoso.onmicrosoft.com"

    # -- Anchor principals (fixed IDs for test assertions) --

    # Overprivileged set: holds Global Admin / Privileged Role Admin but
    # only does mundane work (Teams, Office).  The activity profile does
    # NOT include Azure Management or admin-portal sign-ins.
    OP1_ID = "op000001-0000-0000-0000-000000000001"
    OP2_ID = "op000002-0000-0000-0000-000000000002"
    OP3_ID = "op000003-0000-0000-0000-000000000003"
    OP4_ID = "op000004-0000-0000-0000-000000000004"

    # Dormant set: holds Tier 0 / Tier 1 roles, last sign-in >45 days ago
    DP1_ID = "dp000001-0000-0000-0000-000000000001"
    DP2_ID = "dp000002-0000-0000-0000-000000000002"
    DP3_ID = "dp000003-0000-0000-0000-000000000003"
    DP4_ID = "dp000004-0000-0000-0000-000000000004"

    # Correctly provisioned set: roles match activity; recent sign-ins
    CP1_ID = "cp000001-0000-0000-0000-000000000001"
    CP2_ID = "cp000002-0000-0000-0000-000000000002"
    CP3_ID = "cp000003-0000-0000-0000-000000000003"

    anchor_principals = [
        # Overprivileged accounts
        _make_user(OP1_ID, "Marcus Webb", f"marcus.webb@{domain}", "Member"),
        _make_user(OP2_ID, "Priya Nair", f"priya.nair@{domain}", "Member"),
        _make_user(OP3_ID, "Jordan Ellis", f"jordan.ellis@{domain}", "Member"),
        _make_user(OP4_ID, "Chloe Okonkwo", f"chloe.okonkwo@{domain}", "Guest"),
        # Dormant privileged accounts
        _make_user(DP1_ID, "Ethan Blackwood", f"ethan.blackwood@{domain}", "Member"),
        _make_user(DP2_ID, "Sofia Andersen", f"sofia.andersen@{domain}", "Member"),
        _make_user(
            DP3_ID, "svc-backup-agent", f"svc-backup-agent@{domain}", "ServicePrincipal"
        ),
        _make_user(
            DP4_ID, "svc-deploy-prod", f"svc-deploy-prod@{domain}", "ServicePrincipal"
        ),
        # Correctly provisioned accounts
        _make_user(CP1_ID, "Amara Osei", f"amara.osei@{domain}", "Member"),
        _make_user(CP2_ID, "Henrik Larsson", f"henrik.larsson@{domain}", "Member"),
        _make_user(CP3_ID, "Fatima Al-Rashid", f"fatima.alrashid@{domain}", "Member"),
    ]

    anchor_ids = {u["id"] for u in anchor_principals}
    users.extend(anchor_principals)

    # -- Filler users: regular members, a handful of guests --
    filler_ids: list[str] = []
    for _ in range(89):  # total users ≈ 100 (11 anchor + 89 filler)
        uid = _uuid(fake)
        first = fake.first_name()
        last = fake.last_name()
        upn = f"{first.lower()}.{last.lower()}@{domain}"
        user_type = rng.choices(
            ["Member", "Guest"],
            weights=[90, 10],
        )[0]
        users.append(_make_user(uid, f"{first} {last}", upn, user_type))
        filler_ids.append(uid)

    # ---------------------------------------------------------------
    # 2. Groups
    # ---------------------------------------------------------------
    # Five groups: two role-assignable (Tier 0 and Tier 1), three regular.

    TIER0_GROUP_ID = "grp00000-tier0-0000-0000-000000000001"
    TIER1_GROUP_ID = "grp00000-tier1-0000-0000-000000000002"
    HELPDESK_GROUP_ID = "grp00000-help-0000-0000-000000000003"
    READERS_GROUP_ID = "grp00000-read-0000-0000-000000000004"
    COMPLIANCE_GROUP_ID = "grp00000-comp-0000-0000-000000000005"

    # DP2 inherits Privileged Role Administrator through Tier0-Admins group
    # Some filler users get group memberships for realism
    tier0_members = [DP2_ID, *rng.sample(filler_ids, 2)]
    tier1_members = [CP1_ID, CP2_ID, *rng.sample(filler_ids, 5)]
    helpdesk_members = rng.sample(filler_ids, 8)
    readers_members = rng.sample(filler_ids, 12)
    compliance_members = [CP3_ID, *rng.sample(filler_ids, 4)]

    groups: list[dict[str, Any]] = [
        {
            "id": TIER0_GROUP_ID,
            "displayName": "Tier0-Admins (PIM)",
            "isRoleAssignable": True,
            "members": tier0_members,
            "assignedRoles": [ROLE_BY_NAME["Privileged Role Administrator"][0]],
        },
        {
            "id": TIER1_GROUP_ID,
            "displayName": "Security Operations",
            "isRoleAssignable": True,
            "members": tier1_members,
            "assignedRoles": [ROLE_BY_NAME["Security Administrator"][0]],
        },
        {
            "id": HELPDESK_GROUP_ID,
            "displayName": "IT Helpdesk",
            "isRoleAssignable": False,
            "members": helpdesk_members,
            "assignedRoles": [],
        },
        {
            "id": READERS_GROUP_ID,
            "displayName": "Audit Readers",
            "isRoleAssignable": False,
            "members": readers_members,
            "assignedRoles": [],
        },
        {
            "id": COMPLIANCE_GROUP_ID,
            "displayName": "Compliance Team",
            "isRoleAssignable": True,
            "members": compliance_members,
            "assignedRoles": [ROLE_BY_NAME["Compliance Administrator"][0]],
        },
    ]

    # Build group-display-name lookup by id for role-assignment generation
    group_name_by_id = {g["id"]: g["displayName"] for g in groups}

    # ---------------------------------------------------------------
    # 3. Role assignments
    # ---------------------------------------------------------------
    role_assignments: list[dict[str, Any]] = []
    ra_counter = 0

    def _ra(
        principal_id: str,
        role_name: str,
        assignment_type: str = "direct",
        assigned_via: str | None = None,
        assigned_at: datetime | None = None,
    ) -> dict[str, Any]:
        nonlocal ra_counter
        ra_counter += 1
        rid, _ = ROLE_BY_NAME[role_name]
        if assigned_at is None:
            # Realistic: assignments made 1–24 months before snapshot
            days_ago = rng.randint(30, 730)
            assigned_at = snapshot_date - timedelta(days=days_ago)
        return {
            "id": f"ra-{ra_counter:05d}",
            "principalId": principal_id,
            "roleDefinitionId": rid,
            "roleName": role_name,
            "assignmentType": assignment_type,
            "assignedVia": assigned_via,
            "assignedAt": _ts(assigned_at),
        }

    # -- Overprivileged accounts: high-tier roles, mundane activity profile --
    # OP1: Global Administrator (direct) — only does Teams/Office work
    role_assignments.append(_ra(OP1_ID, "Global Administrator"))
    role_assignments.append(_ra(OP1_ID, "Reports Reader"))

    # OP2: Privileged Role Administrator + User Administrator (direct)
    role_assignments.append(_ra(OP2_ID, "Privileged Role Administrator"))
    role_assignments.append(_ra(OP2_ID, "User Administrator"))

    # OP3: Security Administrator + Exchange Administrator — only basic logins
    role_assignments.append(_ra(OP3_ID, "Security Administrator"))
    role_assignments.append(_ra(OP3_ID, "Exchange Administrator"))

    # OP4: Global Administrator (direct) — guest account, basic sign-ins only
    role_assignments.append(_ra(OP4_ID, "Global Administrator"))

    # -- Dormant privileged accounts: no sign-in within 45+ days --
    # DP1: Global Administrator (direct), last signed in ~60 days ago
    role_assignments.append(_ra(DP1_ID, "Global Administrator"))

    # DP2: Privileged Role Administrator (group-inherited via Tier0-Admins)
    role_assignments.append(
        _ra(
            DP2_ID,
            "Privileged Role Administrator",
            assignment_type="group",
            assigned_via="Tier0-Admins (PIM)",
        )
    )

    # DP3: Application Administrator (service principal) — no sign-in ever
    role_assignments.append(_ra(DP3_ID, "Application Administrator"))

    # DP4: Cloud Application Administrator (service principal) — no sign-in ever
    role_assignments.append(_ra(DP4_ID, "Cloud Application Administrator"))
    role_assignments.append(_ra(DP4_ID, "User Administrator"))

    # -- Correctly provisioned accounts --
    # CP1: Security Administrator via group — active security analyst
    role_assignments.append(
        _ra(
            CP1_ID,
            "Security Administrator",
            assignment_type="group",
            assigned_via="Security Operations",
        )
    )

    # CP2: Security Reader — read-only, appropriate for their role
    role_assignments.append(_ra(CP2_ID, "Security Reader"))

    # CP3: Compliance Administrator via group — active compliance officer
    role_assignments.append(
        _ra(
            CP3_ID,
            "Compliance Administrator",
            assignment_type="group",
            assigned_via="Compliance Team",
        )
    )

    # -- Group-level role assignments (groups hold roles; members inherit them) --
    # Emit one RA per (member, role) pair for group-inherited assignments not yet covered
    for group in groups:
        if not group["assignedRoles"]:
            continue
        grp_display = group["displayName"]
        for member_id in group["members"]:
            # Skip anchor principals already handled above
            if member_id in anchor_ids:
                continue
            for role_def_id in group["assignedRoles"]:
                # Find role name from definition ID
                role_name = next(
                    (n for n, (rid, _) in ROLE_BY_NAME.items() if rid == role_def_id),
                    None,
                )
                if role_name is None:
                    continue
                role_assignments.append(
                    _ra(
                        member_id,
                        role_name,
                        assignment_type="group",
                        assigned_via=grp_display,
                    )
                )

    # -- Filler direct assignments: most filler users get a low-tier role --
    low_tier_roles = ["Directory Readers", "Security Reader", "Reports Reader"]
    for uid in filler_ids:
        # 70% chance of having a direct low-tier role
        if rng.random() < 0.70:
            role_name = rng.choice(low_tier_roles)
            role_assignments.append(_ra(uid, role_name))

    # A few filler users get a Tier 1 role for realism (correctly provisioned)
    tier1_roles = [
        "Helpdesk Administrator",
        "User Administrator",
        "Exchange Administrator",
    ]
    for uid in rng.sample(filler_ids, 6):
        role_assignments.append(_ra(uid, rng.choice(tier1_roles)))

    # ---------------------------------------------------------------
    # 4. Sign-in logs
    # ---------------------------------------------------------------
    sign_in_logs: list[dict[str, Any]] = []
    sl_counter = 0

    def _sl(
        user_id: str,
        display_name: str,
        timestamp: datetime,
        app: str,
        status: str = "Success",
    ) -> dict[str, Any]:
        nonlocal sl_counter
        sl_counter += 1
        return {
            "id": f"sl-{sl_counter:06d}",
            "userId": user_id,
            "userDisplayName": display_name,
            "signInTimestamp": _ts(timestamp),
            "appDisplayName": app,
            "status": status,
            "ipAddress": _fake_ip(rng),
        }

    def _add_active_user_logins(
        uid: str,
        display_name: str,
        apps: list[str],
        count: int = 15,
        recency_days: int = 20,
    ) -> None:
        """Emit *count* sign-in entries spread over the observation window,
        with the most recent within *recency_days* of the snapshot."""
        recent_start = snapshot_date - timedelta(days=recency_days)
        for i in range(count):
            if i < 3:
                # Ensure at least three recent logins
                ts = _random_business_datetime(rng, recent_start, snapshot_date)
            else:
                ts = _random_business_datetime(rng, observation_start, snapshot_date)
            app = rng.choice(apps)
            sign_in_logs.append(_sl(uid, display_name, ts, app))

    # Overprivileged accounts: active sign-ins, but only mundane apps
    mundane_apps = ["Microsoft Teams", "Microsoft Office", "Office 365 Exchange Online"]

    _add_active_user_logins(
        OP1_ID, "Marcus Webb", mundane_apps, count=20, recency_days=5
    )
    _add_active_user_logins(
        OP2_ID, "Priya Nair", mundane_apps, count=18, recency_days=7
    )
    _add_active_user_logins(
        OP3_ID, "Jordan Ellis", mundane_apps, count=15, recency_days=10
    )
    _add_active_user_logins(
        OP4_ID, "Chloe Okonkwo", mundane_apps, count=8, recency_days=14
    )

    # Dormant accounts: last sign-in 45–90 days before snapshot
    def _add_stale_logins(
        uid: str,
        display_name: str,
        days_ago_min: int = 45,
        days_ago_max: int = 85,
        count: int = 5,
    ) -> None:
        stale_end = snapshot_date - timedelta(days=days_ago_min)
        stale_start = snapshot_date - timedelta(days=days_ago_max)
        for _ in range(count):
            ts = _random_business_datetime(rng, stale_start, stale_end)
            app = rng.choice(APP_NAMES)
            sign_in_logs.append(_sl(uid, display_name, ts, app))

    _add_stale_logins(DP1_ID, "Ethan Blackwood", days_ago_min=55, days_ago_max=85)
    _add_stale_logins(DP2_ID, "Sofia Andersen", days_ago_min=45, days_ago_max=80)
    # DP3 and DP4 are service principals — no sign-in entries at all (never signed in)

    # Correctly provisioned accounts: active, apps consistent with role
    admin_apps = [
        "Microsoft Azure Management",
        "Microsoft 365 Admin Center",
        "Azure Active Directory PowerShell",
    ]
    _add_active_user_logins(CP1_ID, "Amara Osei", admin_apps + mundane_apps, count=20)
    _add_active_user_logins(CP2_ID, "Henrik Larsson", admin_apps, count=12)
    _add_active_user_logins(
        CP3_ID, "Fatima Al-Rashid", admin_apps + mundane_apps, count=18
    )

    # Filler users: ~80% have sign-in activity, ~20% have zero (natural churn)
    user_display_map = {u["id"]: u["displayName"] for u in users}
    for uid in filler_ids:
        if rng.random() < 0.80:
            n_logins = rng.randint(1, 25)
            _add_active_user_logins(
                uid,
                user_display_map[uid],
                mundane_apps,
                count=n_logins,
                recency_days=rng.randint(1, 30),
            )

    # ---------------------------------------------------------------
    # 5. Assemble dataset payload
    # ---------------------------------------------------------------
    dataset: dict[str, Any] = {
        "users": users,
        "roleAssignments": role_assignments,
        "signInLogs": sign_in_logs,
        "groups": groups,
    }

    # ---------------------------------------------------------------
    # 6. Ground-truth manifest (for integration tests)
    # ---------------------------------------------------------------
    ground_truth: list[dict[str, Any]] = [
        # --- Overprivileged findings ---
        {
            "principalId": OP1_ID,
            "principalName": "Marcus Webb",
            "category": "overprivileged",
            "expectedSeverity": "critical",
            "reason": (
                "Global Administrator assigned directly; sign-in activity limited to "
                "Teams and Office with no Azure Management or admin-portal access."
            ),
        },
        {
            "principalId": OP2_ID,
            "principalName": "Priya Nair",
            "category": "overprivileged",
            "expectedSeverity": "critical",
            "reason": (
                "Holds both Privileged Role Administrator and User Administrator directly; "
                "sign-in activity limited to mundane productivity apps."
            ),
        },
        {
            "principalId": OP3_ID,
            "principalName": "Jordan Ellis",
            "category": "overprivileged",
            "expectedSeverity": "high",
            "reason": (
                "Security Administrator and Exchange Administrator assigned directly; "
                "no sign-in activity against security or Exchange workloads."
            ),
        },
        {
            "principalId": OP4_ID,
            "principalName": "Chloe Okonkwo",
            "category": "overprivileged",
            "expectedSeverity": "critical",
            "reason": (
                "Guest account with Global Administrator; "
                "B2B guests should never hold Tier 0 directory roles."
            ),
        },
        # --- Dormant privileged findings ---
        {
            "principalId": DP1_ID,
            "principalName": "Ethan Blackwood",
            "category": "dormant_privileged",
            "expectedSeverity": "critical",
            "reason": (
                "Global Administrator with no sign-in for 55–85 days "
                "(well beyond the 30-day dormancy threshold)."
            ),
        },
        {
            "principalId": DP2_ID,
            "principalName": "Sofia Andersen",
            "category": "dormant_privileged",
            "expectedSeverity": "critical",
            "reason": (
                "Privileged Role Administrator inherited via Tier0-Admins group; "
                "no sign-in for 45–80 days."
            ),
        },
        {
            "principalId": DP3_ID,
            "principalName": "svc-backup-agent",
            "category": "dormant_privileged",
            "expectedSeverity": "high",
            "reason": (
                "Service principal with Application Administrator and zero sign-in "
                "activity; standing privilege with no evidence of use."
            ),
        },
        {
            "principalId": DP4_ID,
            "principalName": "svc-deploy-prod",
            "category": "dormant_privileged",
            "expectedSeverity": "high",
            "reason": (
                "Service principal with Cloud Application Administrator and User "
                "Administrator; no sign-in activity ever recorded."
            ),
        },
    ]

    return dataset, ground_truth


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a deterministic synthetic Azure AD tenant snapshot."
    )
    parser.add_argument(
        "--output",
        default="data/sample_dataset.json",
        help="Path for the dataset JSON output file (default: data/sample_dataset.json).",
    )
    parser.add_argument(
        "--ground-truth",
        default="data/ground_truth.json",
        help="Path for the ground-truth findings manifest (default: data/ground_truth.json).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="RNG seed for deterministic output (default: 42).",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        default=True,
        help="Pretty-print JSON output (default: true).",
    )
    args = parser.parse_args()

    dataset, ground_truth = generate(seed=args.seed)

    indent = 2 if args.pretty else None

    # Ensure output directories exist
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    gt_path = Path(args.ground_truth)
    gt_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(dataset, fh, indent=indent, ensure_ascii=False)

    with gt_path.open("w", encoding="utf-8") as fh:
        json.dump(ground_truth, fh, indent=indent, ensure_ascii=False)

    # Summary stats
    n_users = len(dataset["users"])
    n_roles = len({ra["roleDefinitionId"] for ra in dataset["roleAssignments"]})
    n_assignments = len(dataset["roleAssignments"])
    n_sign_ins = len(dataset["signInLogs"])
    n_groups = len(dataset["groups"])

    print(f"Dataset written to   : {output_path}")
    print(f"Ground truth written : {gt_path}")
    print(f"  Users              : {n_users}")
    print(f"  Distinct roles     : {n_roles}")
    print(f"  Role assignments   : {n_assignments}")
    print(f"  Sign-in log entries: {n_sign_ins}")
    print(f"  Groups             : {n_groups}")
    print(f"  Ground-truth flags : {len(ground_truth)}")


if __name__ == "__main__":
    main()
