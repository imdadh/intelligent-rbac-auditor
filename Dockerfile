# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1: builder
# Install all Python dependencies into a local prefix so that only the
# compiled wheels — not build tools — end up in the runtime image.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build-time system dependencies required by some Python packages
# (psycopg2-binary ships its own libpq, but other packages may need gcc).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only the files needed to resolve and install dependencies first so
# that Docker can cache this layer and skip reinstallation when only
# application source changes.
COPY pyproject.toml ./

# Create a stub package structure so that hatchling (the build backend) can
# resolve the project metadata without the full source tree being present.
RUN mkdir -p app scripts

# Install the project and all runtime dependencies into /install so the
# runtime stage can copy a clean, self-contained tree.
RUN pip install --upgrade pip \
    && pip install --no-cache-dir --prefix=/install .

# ---------------------------------------------------------------------------
# Stage 2: runtime
# Lean image that contains only what is needed to run the service.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

# Non-root user for defence-in-depth.  The UID/GID are arbitrary but
# consistent so that volume-mounted files can be owned predictably.
RUN groupadd --gid 1001 appgroup \
    && useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Runtime system libraries (libpq is needed by psycopg2-binary at import time).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy the pre-built Python packages from the builder stage.
COPY --from=builder /install /usr/local

# Copy application source.  Ordering is deliberate: less-frequently changed
# directories first so that source edits invalidate only the final layers.
COPY migrations/ ./migrations/
COPY scripts/ ./scripts/
COPY app/ ./app/

# Copy configuration files required at runtime.
COPY pyproject.toml ./

# Ensure the entrypoint script is executable.  The script itself is added
# in a later sub-task; we copy it here if it already exists.
# Using a glob that silently succeeds when the file is absent is not
# supported in COPY, so we add a conditional approach via a small shell
# command in the entrypoint stage instead.

# Drop to the non-root user for all subsequent instructions and at runtime.
USER appuser

# Expose the port Uvicorn will bind to.  This is documentary; the actual
# binding is controlled by the entrypoint command.
EXPOSE 8000

# Default entrypoint.  docker-compose overrides this with the entrypoint
# script that runs Alembic migrations and seeds the database first.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
