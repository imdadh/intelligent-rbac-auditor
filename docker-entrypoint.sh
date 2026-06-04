#!/usr/bin/env bash
# docker-entrypoint.sh
#
# Container startup sequence for the Intelligent RBAC Policy Auditor.
#
# Steps
# -----
# 1. Run Alembic database migrations (idempotent — safe to run on every start).
# 2. Conditionally seed the synthetic dataset: only if the `datasets` table
#    contains zero rows.  This prevents duplicate data on container restarts
#    while ensuring a first-time visitor immediately has something to audit.
# 3. Start the Uvicorn ASGI server.
#
# Environment variables consumed
# ------------------------------
# DATABASE_URL   Full PostgreSQL connection string, e.g.
#                postgresql://DB_USER:DB_PASSWORD@db:5432/rbac_auditor
#                This variable is always set by docker-compose.yml.

set -euo pipefail

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log() {
    # Emit a simple timestamped line to stdout so startup progress is visible
    # in `docker-compose logs` without requiring the Python app to be running.
    echo "[entrypoint] $(date -u '+%Y-%m-%dT%H:%M:%SZ') $*"
}

# ---------------------------------------------------------------------------
# Step 1 — Apply database migrations
# ---------------------------------------------------------------------------

log "Running Alembic migrations ..."
alembic upgrade head
log "Migrations complete."

# ---------------------------------------------------------------------------
# Step 2 — Seed synthetic dataset (only when the table is empty)
# ---------------------------------------------------------------------------

# Parse the host, port, user, password, and database name out of DATABASE_URL
# so we can query the row count with psql before starting the Python process.
#
# DATABASE_URL format: postgresql://DB_USER:DB_PASSWORD@host:port/dbname
# We use Python for the parse to avoid fragile shell regex and to stay
# consistent with how the application itself reads the URL.
ROW_COUNT=$(python - <<'EOF'
import os
import sys
try:
    from urllib.parse import urlparse
    url = os.environ["DATABASE_URL"]
    # Accept both postgresql:// and postgresql+asyncpg:// schemes.
    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://"))
    import subprocess
    env = os.environ.copy()
    env["PGPASSWORD"] = parsed.password or ""
    result = subprocess.run(
        [
            "psql",
            "--host", parsed.hostname,
            "--port", str(parsed.port or 5432),
            "--username", parsed.username,
            "--dbname", parsed.path.lstrip("/"),
            "--tuples-only",
            "--no-align",
            "--command", "SELECT COUNT(*) FROM datasets;",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        # Table may not exist yet or psql unavailable; default to 0 so we
        # attempt seeding and let the seed script handle errors gracefully.
        print("0")
    else:
        print(result.stdout.strip())
except Exception:
    # Any unexpected failure defaults to 0 (attempt seeding).
    print("0")
EOF
)

# Strip any surrounding whitespace from the count.
ROW_COUNT="$(echo "${ROW_COUNT}" | tr -d '[:space:]')"

if [ "${ROW_COUNT}" = "0" ]; then
    log "Datasets table is empty — seeding synthetic dataset ..."
    python scripts/seed_database.py
    log "Seeding complete."
else
    log "Datasets table already contains ${ROW_COUNT} row(s) — skipping seed."
fi

# ---------------------------------------------------------------------------
# Step 3 — Start the application server
# ---------------------------------------------------------------------------

log "Starting Uvicorn ..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
