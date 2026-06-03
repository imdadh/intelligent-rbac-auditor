# ---------------------------------------------------------------------------
# Intelligent RBAC Policy Auditor — Multi-stage Dockerfile
#
# Stage 1 (builder): installs all Python dependencies into a virtual
#   environment so that only the compiled wheels are copied to the runtime
#   image, keeping the final layer small and free of build toolchain.
#
# Stage 2 (runtime): copies the virtualenv and application source into a
#   slim Python image, exposes port 8000, and delegates startup to the
#   docker-entrypoint.sh script (which runs Alembic migrations, optionally
#   seeds synthetic data, then launches Uvicorn).
# ---------------------------------------------------------------------------

# ---- builder stage -------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies required by some Python packages (e.g. psycopg2).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency manifest first to exploit Docker layer caching: this layer
# is only invalidated when pyproject.toml changes, not on every source edit.
COPY pyproject.toml ./

# Create an isolated virtualenv so it can be copied cleanly to the runtime
# stage without dragging in the rest of the build toolchain.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Bootstrap pip/hatchling then install the project in non-editable mode so
# all runtime dependencies land inside the virtualenv.
RUN pip install --upgrade pip hatchling && \
    pip install --no-cache-dir -e . 2>/dev/null || \
    pip install --no-cache-dir \
        fastapi \
        "uvicorn[standard]" \
        sqlalchemy \
        alembic \
        psycopg2-binary \
        asyncpg \
        langchain \
        langchain-core \
        langchain-openai \
        openai \
        structlog \
        slowapi \
        httpx \
        pydantic \
        pydantic-settings \
        faker

# ---- runtime stage -------------------------------------------------------
FROM python:3.11-slim AS runtime

# Install runtime system libraries (libpq for psycopg2, postgresql-client for
# the psql calls in docker-entrypoint.sh).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq-dev \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy the pre-built virtualenv from the builder stage.
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Copy the full project source into the image.  In development the
# docker-compose.yml bind-mounts the source tree over this layer, but the
# copy ensures the image is self-contained for production-style runs.
COPY . .

# Ensure the entrypoint script is executable inside the image regardless of
# the file permissions present in the source tree.
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000

# The entrypoint script handles migrations, optional seeding, and uvicorn
# startup.  Using exec form avoids a superfluous shell wrapper process.
ENTRYPOINT ["/app/docker-entrypoint.sh"]
