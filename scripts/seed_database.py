#!/usr/bin/env python
"""Seed the database with the synthetic dataset.

This script is invoked by ``docker-entrypoint.sh`` at container startup when
the ``datasets`` table is empty.  It can also be run directly during local
development to populate a fresh database:

    python scripts/seed_database.py

Behaviour
---------
- Loads the synthetic dataset JSON produced by ``generate_synthetic_data.py``
  (expected at ``scripts/sample_dataset.json``).
- Inserts a single ``Dataset`` record into the database.
- Logs the resulting dataset ID to stdout.
- Exits with code 0 on success, non-zero on failure.

The script is intentionally simple: it writes directly via SQLAlchemy rather
than going through the HTTP API so that it works before uvicorn is running.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Minimal stdlib logging so progress is visible in docker-compose logs.
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [seed_database] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    stream=sys.stdout,
)
log = logging.getLogger("seed_database")

# ---------------------------------------------------------------------------
# Locate the sample dataset
# ---------------------------------------------------------------------------

SCRIPTS_DIR = Path(__file__).parent.resolve()
SAMPLE_DATA_PATH = SCRIPTS_DIR / "sample_dataset.json"


def load_sample_dataset() -> dict:
    """Load and return the synthetic dataset JSON.

    Raises
    ------
    SystemExit
        If the sample dataset file does not exist.
    """
    if not SAMPLE_DATA_PATH.exists():
        log.error(
            "Sample dataset not found at %s. "
            "Run 'python scripts/generate_synthetic_data.py' first.",
            SAMPLE_DATA_PATH,
        )
        sys.exit(1)

    log.info("Loading sample dataset from %s", SAMPLE_DATA_PATH)
    with SAMPLE_DATA_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Database interaction
# ---------------------------------------------------------------------------


def seed(dataset_json: dict) -> None:
    """Persist the dataset JSON as a single ``Dataset`` row.

    Parameters
    ----------
    dataset_json:
        The full synthetic dataset loaded from ``sample_dataset.json``.
    """
    # Import here so that the script can be imported without triggering
    # SQLAlchemy engine creation at module load time.
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://rbac_user:rbac_password@localhost:5432/rbac_auditor",
    )

    # asyncpg scheme is not compatible with the synchronous engine used here;
    # normalise the scheme so this script works with either URL format.
    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    log.info("Connecting to database ...")
    engine = create_engine(sync_url, echo=False)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        # Guard: if at least one dataset row exists, skip insertion so the
        # script remains idempotent when called outside of the entrypoint.
        count_result = session.execute(text("SELECT COUNT(*) FROM datasets"))
        existing_count = count_result.scalar_one()
        if existing_count > 0:
            log.info(
                "Database already contains %d dataset(s) — skipping seed.",
                existing_count,
            )
            return

        user_count = len(dataset_json.get("users", []))

        # Build a raw INSERT so we do not depend on the ORM model being
        # fully implemented at this early stage of the project.  Once the
        # Dataset model exists this can be replaced with a model instantiation.
        import uuid

        dataset_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        session.execute(
            text("""
                INSERT INTO datasets (id, name, raw_data, user_count, created_at)
                VALUES (:id, :name, :raw_data, :user_count, :created_at)
                """),
            {
                "id": dataset_id,
                "name": "Synthetic Azure AD Snapshot (auto-seeded)",
                "raw_data": json.dumps(dataset_json),
                "user_count": user_count,
                "created_at": now,
            },
        )
        session.commit()

    log.info(
        "Seed complete. Dataset ID: %s  Users: %d",
        dataset_id,
        user_count,
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        data = load_sample_dataset()
        seed(data)
    except Exception as exc:
        log.exception("Seeding failed: %s", exc)
        sys.exit(1)
