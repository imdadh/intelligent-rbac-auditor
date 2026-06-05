#!/usr/bin/env python
"""Seed the database with the synthetic dataset.

This script is invoked by ``docker-entrypoint.sh`` at container startup when
the ``datasets`` table is empty.  It can also be run directly during local
development to populate a fresh database:

    python scripts/seed_database.py

Behaviour
---------
- Loads the synthetic dataset JSON produced by ``generate_synthetic_data.py``
  (expected at ``data/sample_dataset.json``).
- Inserts a single ``Dataset`` record via the `ingest_dataset` service.
- Logs the resulting dataset ID to stdout.
- Exits with code 0 on success, non-zero on failure.

The script is intentionally simple: it calls the same ingestion logic that the
REST API uses, ensuring validation and cross-reference checks are applied.
"""

from __future__ import annotations

import json
import logging
import sys
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

# Project root is two levels up from this script (scripts/ -> project root).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DATA_PATH = PROJECT_ROOT / "data" / "sample_dataset.json"


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
    """Persist the dataset via the ingestion service.

    Parameters
    ----------
    dataset_json:
        The full synthetic dataset loaded from ``sample_dataset.json``.
    """
    # Set up a database session using the application's configuration.
    from sqlalchemy.orm import Session

    from app.models.base import SessionLocal, _ensure_session_factory_bound

    # Ensure the engine and session factory are initialised.
    _ensure_session_factory_bound()
    db: Session = SessionLocal()

    try:
        # Guard: if at least one dataset row exists, skip insertion so the
        # script remains idempotent when called outside of the entrypoint.
        from app.models.dataset import Dataset

        existing_count = db.query(Dataset).count()
        if existing_count > 0:
            log.info(
                "Database already contains %d dataset(s) — skipping seed.",
                existing_count,
            )
            return

        # Use the validated ingestion service to parse and persist.
        from app.services.ingestion import ingest_dataset

        dataset = ingest_dataset(
            name="Synthetic Azure AD Snapshot (auto-seeded)",
            data=dataset_json,
            db=db,
        )
        db.commit()

        log.info(
            "Seed complete. Dataset ID: %s  Users: %d",
            dataset.id,
            dataset.user_count,
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


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
