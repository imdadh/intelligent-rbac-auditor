# Intelligent RBAC Policy Auditor

Enterprise Azure AD environments accumulate role assignments over time — Global Admin grants from migrations that were never revoked, nested group memberships that silently escalate privilege, and service accounts with standing permissions last exercised eighteen months ago. The **Intelligent RBAC Policy Auditor** is a production-grade Python service that ingests an Azure AD role-assignment export (synthetic JSON), runs it through a structured LLM analysis pipeline powered by LangChain, and surfaces actionable findings: overprivileged accounts and dormant privileged role assignments. The service produces both a structured JSON report and a human-readable Markdown narrative, and exposes a natural-language query interface so security engineers can explore the data interactively — no spreadsheet queries required.

---

## Setup

> Detailed setup instructions will be added here once the core service is implemented.
