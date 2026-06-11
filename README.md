# Intelligent RBAC Policy Auditor

Enterprise Azure AD environments accumulate role assignments like sediment — Global Admin grants made during a migration that were never revoked, nested group memberships that silently escalate privilege, service accounts with standing permissions they exercised once eighteen months ago. Auditing these assignments by hand is tedious, error-prone, and rarely done with the frequency the risk warrants.

The **Intelligent RBAC Policy Auditor** is a production-grade Python service that ingests an Azure AD role-assignment export (synthetic JSON for this portfolio phase), runs it through a structured LLM analysis pipeline, and produces actionable findings: overprivileged accounts, dormant privileged role assignments, role-bloat patterns, and least-privilege violations. The service outputs both a structured JSON report and a human-readable narrative explaining each finding in plain language. It also exposes a natural-language query interface so that a security engineer can ask questions like *"show users with Global Admin who haven't used it in 30 days"* and get an immediate, contextualized answer.

This project demonstrates real-world enterprise IAM expertise — the same audit work I do by hand against Entra ID — augmented with structured LLM analysis and wrapped in a service that looks and behaves like production software.

---

## Architecture

```mermaid
flowchart TB
    subgraph External
        User["Security Engineer / Demo Visitor"]
        SampleData["Synthetic Dataset (JSON)"]
    end

    subgraph FastAPI Service
        API["REST API (FastAPI)"]
        WebUI["Web UI (SPA)"]
        Ingestion["Dataset Ingestion"]
        AuditPipeline["Audit Pipeline"]
        Preprocessor["Pre-processor"]
        LLM["LLM Provider (LangChain)"]
        ReportGen["Report Generator"]
        QueryEngine["Query Engine"]
    end

    subgraph Infrastructure
        DB[(PostgreSQL)]
        Logs["Structured Logging (structlog)"]
        RateLimiter["Rate Limiter (slowapi)"]
        Auth["Optional API Key Auth"]
    end

    User -->|Upload / Interact| API
    User -->|View UI| WebUI
    SampleData -->|POST /api/v1/datasets| API
    API --> Ingestion
    Ingestion --> DB
    API --> AuditPipeline
    AuditPipeline --> Preprocessor
    Preprocessor --> LLM
    LLM --> AuditPipeline
    AuditPipeline --> DB
    API --> ReportGen
    ReportGen --> DB
    API --> QueryEngine
    QueryEngine --> LLM
    QueryEngine --> DB
    WebUI --> API
    API --> Auth
    API --> RateLimiter
    API ---> Logs
```

**Key components:**
- **FastAPI Service** — Handles HTTP requests, serves the web UI, and orchestrates the audit pipeline.
- **PostgreSQL** — Persistent storage for datasets, audits, findings, and query logs.
- **LLM Provider** — Pluggable interface (OpenAI or Azure OpenAI) using LangChain for structured output parsing.
- **Pre-processor** — Computes derived features (days since last sign-in, role tier, assignment type) before LLM analysis to reduce token consumption and improve consistency.
- **Web UI** — Single-page application (HTML/CSS/JS) guiding the user through load → audit → view → query.

---

## Quick Start (Docker)

### Prerequisites
- Docker and Docker Compose installed on your machine.
- (Optional) An OpenAI API key if you want to use the live LLM. Without one, the pipeline runs with mocked LLM responses (still demonstrates the full audit flow).

### Steps

1. Clone the repository:
   ```bash
   git clone https://github.com/your-org/intelligent-rbac-auditor.git
   cd intelligent-rbac-auditor
   ```

2. (Optional) Set your OpenAI API key in a `.env` file (copy from `.env.example`):
   ```bash
   cp .env.example .env
   # Edit .env and set OPENAI_API_KEY=sk-...
   ```

3. Start the service:
   ```bash
   docker-compose up --build
   ```

   The first startup will:
   - Build the Docker image
   - Start PostgreSQL
   - Run database migrations (Alembic)
   - Seed a synthetic dataset (100 users, 15 roles, 90 days of sign-in logs)
   - Start the FastAPI service on port 8000

4. Open your browser and go to [http://localhost:8000](http://localhost:8000).

   You should see the web UI with a "Load Sample Data" button. Click it, then trigger an audit, and explore the findings.

5. (Optional) Access the interactive API documentation at [http://localhost:8000/docs](http://localhost:8000/docs).

---

## API Reference

Full API documentation is auto-generated and available at `/docs` (Swagger UI) or `/redoc` (ReDoc) when the service is running.

### Key Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check (returns `{"status": "ok"}`) |
| `POST` | `/api/v1/datasets` | Upload a dataset (JSON body) |
| `GET` | `/api/v1/datasets/{id}` | Retrieve dataset metadata |
| `POST` | `/api/v1/datasets/sample` | Load the built-in synthetic dataset |
| `POST` | `/api/v1/audits` | Start an audit (returns audit ID, status `pending`) |
| `GET` | `/api/v1/audits/{id}` | Poll audit status and retrieve findings |
| `GET` | `/api/v1/audits/{id}/report?format=json\|markdown` | Get structured or narrative report |
| `POST` | `/api/v1/query` | Ask a natural-language question about a dataset |

All responses follow a consistent envelope:
```json
{
  "data": { ... },
  "meta": { ... }
}
```

Error responses use:
```json
{
  "error": {
    "code": "...",
    "message": "..."
  }
}
```

---

## Sample Usage

### Using the Web UI

1. Open `http://localhost:8000`.
2. Click **Load Sample Data** — this creates a dataset from the pre-seeded synthetic data.
3. Click **Run Audit** — the audit pipeline runs asynchronously. Poll the status until completed.
4. View findings grouped by severity (color-coded badges). Expand each finding to see the narrative and remediation.
5. Use the chat input to ask questions like:
   - *"Which users have Global Administrator and haven't signed in for 30 days?"*
   - *"How many service accounts have privileged roles?"*
   - *"Show all role assignments inherited through groups."*

### Using curl

```bash
# Load sample dataset
DATASET_ID=$(curl -s -X POST http://localhost:8000/api/v1/datasets/sample | jq -r '.data.id')

# Start an audit
AUDIT_ID=$(curl -s -X POST http://localhost:8000/api/v1/audits \
  -H "Content-Type: application/json" \
  -d "{\"dataset_id\": \"$DATASET_ID\"}" | jq -r '.data.id')

# Poll until completed
while true; do
  STATUS=$(curl -s http://localhost:8000/api/v1/audits/$AUDIT_ID | jq -r '.data.status')
  echo "Status: $STATUS"
  if [ "$STATUS" = "completed" ]; then break; fi
  sleep 2
done

# Get the JSON report
curl -s http://localhost:8000/api/v1/audits/$AUDIT_ID/report?format=json | jq '.'

# Get the Markdown narrative report
curl -s http://localhost:8000/api/v1/audits/$AUDIT_ID/report?format=markdown

# Ask a natural-language query
curl -s -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d "{\"dataset_id\": \"$DATASET_ID\", \"question\": \"Show users with Global Admin who haven't signed in for 30 days\"}" | jq '.'
```

---

## Configuration

Key environment variables (see `.env.example` for defaults):

| Variable | Purpose | Default |
|----------|---------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://rbac_user:rbac_password@localhost:5432/rbac_auditor` |
| `LLM_PROVIDER` | LLM backend (`openai` or `azure_openai`) | `openai` |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key | — |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint | — |
| `AZURE_OPENAI_DEPLOYMENT` | Azure OpenAI deployment name | — |
| `AUTH_ENABLED` | Enable API key authentication | `false` |
| `API_KEY` | Expected API key (when auth enabled) | — |
| `RATE_LIMIT_PER_MINUTE` | Max requests per minute per client | `60` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `DORMANT_THRESHOLD_DAYS` | Days of inactivity to flag dormant | `30` |

---

## Development

### Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run unit tests (fast, no database needed)
pytest tests/unit -v

# Run integration tests (requires Docker with PostgreSQL)
docker-compose up -d db
pytest tests/integration -v

# Measure coverage
pytest --cov=app --cov-report=term-missing
```

### Generating Fresh Synthetic Data

```bash
python -m scripts.generate_synthetic_data
```

This writes a deterministic JSON payload to stdout (seeded, reproducible).

### Database Migrations

After modifying models, generate a new Alembic migration:
```bash
alembic revision --autogenerate -m "description"
alembic upgrade head
```

---

## Project Structure

```
intelligent-rbac-auditor/
├── app/
│   ├── api/              # FastAPI route handlers
│   ├── core/             # Configuration, logging, rate-limiting, auth
│   ├── models/           # SQLAlchemy ORM models
│   ├── schemas/          # Pydantic request/response schemas
│   ├── services/         # Business logic (pipeline, preprocessor, query engine, ingestion)
│   ├── llm/              # LLM provider interface (abstract base, OpenAI, Azure OpenAI) and prompts
│   └── static/           # Web UI assets (HTML, CSS, JS)
├── scripts/              # Synthetic data generator, database seeder
├── migrations/           # Alembic migration files
├── tests/                # Unit and integration tests
├── tasks/                # PRD and planning documents
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

---

## License

MIT
