# Contributing

This document describes how to set up a local development environment and
contribute to the Intelligent RBAC Policy Auditor.

## Prerequisites

- Python 3.11 or later
- Docker and Docker Compose (for the full-stack workflow)
- PostgreSQL 15 (if running the service outside Docker)

## Local setup

```bash
# 1. Clone the repository and enter the project root.
git clone <repo-url>
cd intelligent-rbac-auditor

# 2. Create and activate a virtual environment.
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. Install the project and its dev dependencies.
pip install -e ".[dev]"

# 4. Copy the environment template and fill in your values.
cp .env.example .env
```

## Running with Docker Compose

```bash
docker-compose up --build
```

This starts PostgreSQL, runs Alembic migrations, seeds the synthetic dataset,
and launches the FastAPI service on <http://localhost:8000>.

## Running tests

```bash
# Unit tests only (no database required)
pytest tests/unit -v

# Full suite with coverage
pytest --cov=app --cov-report=term-missing
```

## Code style

All Python code is formatted and linted with [Ruff](https://docs.astral.sh/ruff/).

```bash
# Check
ruff check .

# Auto-fix
ruff check --fix .
```

Please ensure `ruff check .` passes before opening a pull request.

## Branch workflow

1. Branch from `feature/intelligent-rbac-auditor` for new work.
2. Keep commits focused; one logical change per commit.
3. Open a pull request against the feature branch and request review.
