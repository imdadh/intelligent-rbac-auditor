# PRD: Intelligent RBAC Policy Auditor

| Field | Value |
|-------|-------|
| **Slug** | `intelligent-rbac-auditor` |
| **Phase** | `phase_1_bridge` |
| **Created** | 2025-01-15 |
| **Status** | Draft |
| **Author** | Imdad |
| **Tech Stack** | Python, FastAPI, LangChain, Azure AD Graph API (mocked), PostgreSQL, SQLAlchemy, Pytest, Docker |

---

## 1. Introduction / Overview

Enterprise Azure AD environments accumulate role assignments like sediment — Global Admin grants made during a migration that were never revoked, nested group memberships that silently escalate privilege, service accounts with standing permissions they exercised once eighteen months ago. Auditing these assignments by hand is tedious, error-prone, and rarely done with the frequency the risk warrants.

The **Intelligent RBAC Policy Auditor** is a production-grade Python service that ingests an Azure AD role-assignment export (synthetic JSON for this portfolio phase), runs it through a structured LLM analysis pipeline, and produces actionable findings: overprivileged accounts, dormant privileged role assignments, role-bloat patterns, and least-privilege violations. The service outputs both a structured JSON report and a human-readable narrative explaining each finding in plain language. It also exposes a natural-language query interface so that a security engineer can ask questions like *"show users with Global Admin who haven't used it in 30 days"* and get an immediate, contextualized answer.

This project demonstrates real-world enterprise IAM expertise — the same audit work I do by hand against Entra ID — augmented with structured LLM analysis and wrapped in a service that looks and behaves like production software.

---

## 2. Goals

1. **Demonstrate enterprise IAM depth.** The service should reflect genuine understanding of Azure AD RBAC concepts — directory roles, role-assignable groups, sign-in activity, privilege tiers — not a toy abstraction.

2. **Show practical LLM application in a security workflow.** The LLM is a tool in the pipeline, not the product. It analyzes structured data, classifies findings, generates narratives, and answers natural-language queries. The architecture should make clear that the LLM is interchangeable and governed.

3. **Deliver production-readiness signals.** Structured logging, rate-limiting, integration tests against synthetic data, Dockerized deployment, clean API design, environment-based configuration. A hiring manager or senior engineer reviewing the repo should see habits, not just features.

4. **Ship a public demo with sanitized sample data.** Anyone who visits the repo can spin up the service, load the sample dataset, trigger an audit, and interact with findings — no Azure subscription required.

5. **Phase 1 scope: overprivileged accounts + dormant privileged role detection.** Keep the finding categories tight. Get two categories working well end-to-end rather than five categories working poorly.

---

## 3. User Stories

### US-1: Security Engineer — Run an Audit
> As a security engineer, I want to upload or point the service at an Azure AD role-assignment export and receive a structured audit report, so that I can quickly identify the highest-risk role assignments in my tenant without manually cross-referencing spreadsheets.

### US-2: Security Engineer — Read the Narrative
> As a security engineer, I want each finding accompanied by a plain-language explanation of *why* it's a risk and *what* to do about it, so that I can paste the finding directly into a ticket or executive summary without rewriting it.

### US-3: Security Engineer — Ask Follow-Up Questions
> As a security engineer, I want to ask natural-language questions about the dataset (e.g., "which service accounts have Privileged Role Administrator?"), so that I can explore the data interactively without writing queries or filters by hand.

### US-4: Hiring Manager — Evaluate the Repository
> As a hiring manager reviewing this portfolio project, I want to see clean code structure, comprehensive tests, Docker-based deployment, and clear documentation, so that I can assess the candidate's production engineering habits.

### US-5: Demo Visitor — Try It Out
> As someone visiting the public demo, I want to load sample data, trigger an audit, and interact with findings through a minimal web UI, so that I can understand what the service does in under five minutes.

---

## 4. Functional Requirements

### Data Ingestion

**FR-1.** The system must accept a synthetic Azure AD role-assignment export in JSON format via a REST API endpoint (`POST /api/v1/datasets`). The payload represents a point-in-time snapshot of a tenant's role assignments, group memberships, and user sign-in activity.

**FR-2.** The system must validate the uploaded JSON against a defined schema and return clear error messages for malformed or incomplete data. Validation should check for required fields: user identifiers, role assignment details, assignment timestamps, and sign-in log entries.

**FR-3.** The system must persist ingested datasets in PostgreSQL via SQLAlchemy, associating each dataset with a unique identifier and ingestion timestamp so that multiple datasets can coexist and audits can reference specific snapshots.

**FR-4.** The system must ship with a built-in synthetic dataset generator (CLI command or script) that produces a medium-fidelity enterprise snapshot: approximately 100 users, approximately 15 Azure AD directory roles, nested group memberships, and simulated sign-in logs spanning the past 90 days. The generated data must be deterministic (seeded) so that tests are reproducible.

### Audit Pipeline

**FR-5.** The system must expose a REST API endpoint (`POST /api/v1/audits`) that accepts a dataset identifier and triggers the analysis pipeline. The endpoint must return immediately with an audit ID and status `pending`; processing happens asynchronously.

**FR-6.** The system must provide a status-polling endpoint (`GET /api/v1/audits/{audit_id}`) that returns the current state of the audit (`pending`, `running`, `completed`, `failed`) and, upon completion, the full results.

**FR-7.** The analysis pipeline must detect **overprivileged accounts**: users or service principals whose assigned roles grant permissions significantly beyond what their sign-in activity and usage patterns suggest they need. The pipeline must consider role tier (e.g., Global Admin vs. Reports Reader), assignment type (direct vs. group-inherited), and activity signals.

**FR-8.** The analysis pipeline must detect **dormant privileged role assignments**: role assignments to users who have not signed in or exercised the role's capabilities within a configurable time window (default: 30 days).

**FR-9.** The analysis pipeline must use an LLM (via LangChain) to classify and reason about findings. The LLM receives structured, pre-processed data — not raw JSON dumps — along with a system prompt that defines the classification criteria, risk tiers, and output schema. The pipeline must enforce structured output parsing so that LLM responses conform to the expected finding schema.

**FR-10.** The system must implement a pluggable LLM provider interface supporting both OpenAI and Azure OpenAI as backends. The active provider must be configurable via environment variables. Swapping providers must not require code changes beyond configuration.

**FR-11.** The pipeline must include a pre-processing stage that computes derived features before LLM analysis: days since last sign-in, role tier classification, direct vs. inherited assignment lineage, and count of privileged roles per user. These features reduce LLM token consumption and improve consistency.

### Report Generation

**FR-12.** Upon audit completion, the system must produce a **structured JSON report** containing: audit metadata (ID, dataset ID, timestamp, parameters), a summary (total users analyzed, total findings, findings by category, findings by severity), and an array of individual findings.

**FR-13.** Each finding in the JSON report must include: a unique finding ID, category (`overprivileged` or `dormant_privileged`), severity (`critical`, `high`, `medium`, `low`), the affected principal (user/service principal identifier and display name), the relevant role assignment(s), supporting evidence (e.g., days since last sign-in, usage metrics), a recommended remediation action, and a human-readable narrative explanation.

**FR-14.** The system must produce a **human-readable narrative report** (Markdown format) that summarizes the audit in executive-friendly language, groups findings by severity, and explains each finding in 2–4 sentences of plain language. This report must be retrievable via API (`GET /api/v1/audits/{audit_id}/report?format=markdown`).

### Natural-Language Query Interface

**FR-15.** The system must expose a REST API endpoint (`POST /api/v1/query`) that accepts a natural-language question and a dataset identifier, interprets the question against the loaded dataset, and returns a structured answer.

**FR-16.** The query interface must handle questions about role assignments, user activity, group membership, and audit findings. Examples: "Show users with Global Admin who haven't signed in for 30 days," "Which groups grant Privileged Role Administrator?", "How many users have more than 3 privileged roles?"

**FR-17.** The query endpoint must return both a structured data payload (JSON array of matching records or computed values) and a natural-language summary of the answer.

**FR-18.** The query interface must gracefully handle questions it cannot answer — returning a clear message indicating the limitation rather than hallucinated data.

### Minimal Web UI

**FR-19.** The system must serve a minimal web-based chat interface at the root URL (`/`) that allows a visitor to: load the sample dataset, trigger an audit, view the narrative report, and ask natural-language questions against the dataset.

**FR-20.** The web UI must be a single-page application — HTML, CSS, and vanilla JavaScript (or a lightweight framework like Alpine.js or htmx). No heavy frontend build pipeline. The UI communicates with the FastAPI backend via the REST API.

**FR-21.** The web UI must display audit findings in a readable format: severity badges, expandable finding details, and the narrative explanation for each finding.

### Production Readiness

**FR-22.** The system must implement structured JSON logging (using Python's `logging` module or `structlog`) with configurable log levels via environment variable. All API requests, pipeline stages, and LLM calls must be logged with correlation IDs.

**FR-23.** The system must implement rate-limiting on all API endpoints (configurable via environment variable, default: 60 requests/minute per client). Rate-limit responses must return standard `429 Too Many Requests` with a `Retry-After` header.

**FR-24.** The system must include a health check endpoint (`GET /health`) that verifies database connectivity and returns service status.

**FR-25.** The system must be deployable via Docker. The repository must include a `Dockerfile` and a `docker-compose.yml` that brings up the FastAPI service and PostgreSQL with a single `docker-compose up` command.

**FR-26.** The `docker-compose.yml` must include a startup sequence that runs database migrations (Alembic) and seeds the synthetic dataset automatically, so that a first-time visitor can interact with the demo immediately.

### Authentication (Optional)

**FR-27.** The system must support optional API key authentication, toggled via an environment variable (`AUTH_ENABLED=true|false`, default `false`). When enabled, all API endpoints except `/health` must require a valid API key in the `Authorization` header. When disabled, all endpoints are open.

### Testing

**FR-28.** The repository must include integration tests (Pytest) that exercise the full audit pipeline against the synthetic dataset: data ingestion, pipeline execution, finding generation, and report output. Tests must assert that known overprivileged and dormant accounts in the synthetic data are correctly identified.

**FR-29.** The repository must include unit tests for the pre-processing stage, schema validation, and provider interface. LLM calls in unit tests must be mocked.

**FR-30.** Test coverage must be measurable and reported. Target: ≥80% line coverage on core modules (pipeline, models, API routes).

---

## 5. Non-Goals (Out of Scope)

The following are explicitly **not** in scope for Phase 1:

- **Live Azure AD / Entra ID integration.** The service works against synthetic JSON exports only. There is no OAuth flow, no Graph API calls, and no real tenant connectivity in this phase.
- **Role-bloat pattern detection.** This finding category is planned for a future phase. Phase 1 focuses exclusively on overprivileged and dormant privileged role detection.
- **Least-privilege violation analysis.** Also deferred to a future phase.
- **Multi-tenant support.** The service handles one dataset at a time conceptually. There is no tenant isolation, organization hierarchy, or multi-user workspace.
- **Persistent user accounts or sessions.** The optional auth is a simple API key gate, not a user management system.
- **CI/CD pipeline configuration.** While the project should be CI-friendly, configuring GitHub Actions or similar is not a deliverable.
- **Production deployment to cloud infrastructure.** The demo runs locally via Docker. Cloud deployment (Azure Container Apps, etc.) is a future concern.
- **Fine-tuning or training custom LLM models.** The service uses general-purpose LLMs via API with carefully crafted prompts.
- **Real-time streaming of audit results.** The polling-based async pattern is sufficient for Phase 1.

---

## 6. Design Considerations

### API Design

- Follow RESTful conventions. Use plural nouns for resource endpoints (`/datasets`, `/audits`). Return appropriate HTTP status codes (201 for creation, 202 for accepted async work, 404 for not found, 422 for validation errors).
- All API responses should follow a consistent envelope: `{ "data": ..., "meta": { ... } }` for success, `{ "error": { "code": "...", "message": "..." } }` for errors.
- API documentation should be auto-generated via FastAPI's built-in OpenAPI/Swagger UI at `/docs`.

### Web UI

- The chat interface should be visually clean and minimal. A dark-themed, single-column layout is appropriate — this is a security tool, not a consumer app.
- The UI should show a clear flow: (1) load data → (2) run audit → (3) view findings → (4) ask questions. A sidebar or stepper pattern can guide the user.
- Findings should use color-coded severity badges: red for critical, orange for high, yellow for medium, gray for low.

### Synthetic Data

- The synthetic dataset should feel real. Use plausible display names (not "User1"), realistic role names matching actual Azure AD directory roles (Global Administrator, User Administrator, Security Reader, etc.), and sign-in patterns that include weekday clustering, occasional off-hours access, and some accounts with zero activity.
- Include at least 3-4 accounts that are clearly overprivileged and 3-4 that are clearly dormant so that the audit pipeline has unambiguous positive cases. Include several accounts that are borderline or correctly provisioned to ensure the pipeline doesn't flag everything.

---

## 7. Technical Considerations

### Project Structure

```
intelligent-rbac-auditor/
├── app/
│   ├── api/              # FastAPI route handlers
│   ├── core/             # Configuration, logging, rate-limiting
│   ├── models/           # SQLAlchemy models
│   ├── schemas/          # Pydantic request/response schemas
│   ├── services/         # Business logic (pipeline, query engine)
│   ├── llm/              # LangChain provider interface, prompts
│   └── static/           # Web UI assets (HTML, CSS, JS)
├── scripts/              # Synthetic data generator
├── migrations/           # Alembic migration files
├── tests/
│   ├── unit/
│   └── integration/
├── tasks/                # PRD and planning documents
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

### LLM Provider Interface

- Define an abstract base class (e.g., `BaseLLMProvider`) with methods like `analyze_findings(preprocessed_data) -> List[Finding]` and `answer_query(question, context) -> QueryResponse`.
- Implement `OpenAIProvider` and `AzureOpenAIProvider` as concrete classes.
- Provider selection via `LLM_PROVIDER` environment variable (`openai` or `azure_openai`). API keys, endpoints, model names, and deployment names configured via environment variables.
- All LLM calls must include retry logic with exponential backoff (3 attempts, configurable).

### LangChain Usage

- Use LangChain for prompt templating, output parsing (structured output with Pydantic models), and the conversational query chain.
- Keep prompt templates in version-controlled files (not inline strings) for reviewability.
- The query interface should use a retrieval-augmented pattern: the dataset context is injected into the prompt, not stored in a vector database (the dataset is small enough for direct context injection in Phase 1).

### Database

- PostgreSQL for persistence. Tables: `datasets`, `audits`, `findings`, `query_logs`.
- Use Alembic for migrations. The initial migration should create all tables.
- SQLAlchemy async support is preferred (using `asyncpg`) to align with FastAPI's async handlers, but synchronous SQLAlchemy is acceptable if async adds unnecessary complexity in Phase 1.

### Async Processing

- For Phase 1, the audit pipeline can run in a background thread or use FastAPI's `BackgroundTasks`. A full task queue (Celery, etc.) is not required.
- The polling endpoint (`GET /api/v1/audits/{audit_id}`) is the mechanism for checking completion status.

### Environment Variables

Key configuration variables the service should support:

| Variable | Purpose | Default |
|----------|---------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://...` (compose default) |
| `LLM_PROVIDER` | `openai` or `azure_openai` | `openai` |
| `OPENAI_API_KEY` | API key for OpenAI | — |
| `AZURE_OPENAI_API_KEY` | API key for Azure OpenAI | — |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint URL | — |
| `AZURE_OPENAI_DEPLOYMENT` | Deployment/model name | — |
| `AUTH_ENABLED` | Enable API key auth | `false` |
| `API_KEY` | Expected API key (when auth enabled) | — |
| `RATE_LIMIT_PER_MINUTE` | Max requests per minute per client | `60` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `DORMANT_THRESHOLD_DAYS` | Days of inactivity to flag dormant | `30` |

### Dependencies

- **Python 3.11+**
- **FastAPI** + **Uvicorn** — web framework and ASGI server
- **SQLAlchemy 2.0** + **Alembic** — ORM and migrations
- **LangChain** — LLM orchestration, prompt management, output parsing
- **Pydantic v2** — schema validation (already bundled with FastAPI)
- **structlog** or standard `logging` — structured logging
- **slowapi** — rate-limiting middleware for FastAPI
- **httpx** — async HTTP client (for LLM API calls if needed)
- **Pytest** + **pytest-asyncio** + **pytest-cov** — testing
- **Faker** — synthetic data generation

---

## 8. Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Audit accuracy** | ≥90% of known overprivileged/dormant accounts in the synthetic dataset are correctly flagged | Integration test assertions |
| **False positive rate** | ≤20% of findings are false positives against the synthetic dataset | Manual review of audit output against synthetic data ground truth |
| **API response time (non-audit)** | p95 < 500ms for data ingestion, status polling, and query endpoints | Logged response times |
| **Audit pipeline completion** | Full audit on the 100-user synthetic dataset completes in < 60 seconds | Timed integration test |
| **Test coverage** | ≥80% line coverage on `app/` modules | `pytest-cov` report |
| **Demo startup time** | `docker-compose up` to interactive demo in < 2 minutes | Manual verification |
| **Documentation completeness** | README includes: project overview, architecture diagram, setup instructions, API reference link, and sample usage | Review checklist |
| **Portfolio signal clarity** | A reviewer can understand the project's purpose, technical choices, and IAM relevance within 5 minutes of reading the README | Peer review |

---

## 9. Open Questions

1. **LLM cost management for the demo.** Should we set a hard token budget per audit run or per query, and if so, what's a reasonable ceiling? The synthetic dataset is small, but unbounded queries could get expensive during open demos.

2. **Prompt versioning.** Should prompts be versioned alongside code (e.g., `v1/overprivileged_analysis.txt`), or is git history sufficient for traceability in Phase 1?

3. **Borderline finding thresholds.** For overprivileged detection, what heuristics define the boundary between "correctly provisioned" and "overprivileged"? This likely needs iteration — should we start with a conservative threshold (flag more) or a strict one (flag less)?

4. **Narrative tone.** Should the human-readable report target a technical audience (SOC analyst) or a mixed audience (including non-technical stakeholders like compliance managers)? This affects vocabulary and explanation depth.

5. **Future phase planning.** Should the data model and pipeline architecture be designed now to accommodate role-bloat and least-privilege analysis in Phase 2, or should we optimize for Phase 1 simplicity and refactor later?

6. **Demo hosting.** If we want the demo accessible without requiring visitors to run Docker locally, should we plan for a lightweight cloud deployment (e.g., Railway, Render, Azure Container Apps) even though it's out of scope for Phase 1 deliverables?