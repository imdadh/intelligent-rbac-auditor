from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.llm.base import BaseLLMProvider
from app.schemas.finding import FindingSchema
from app.schemas.query import QueryResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal Pydantic models for LLM output parsing
# ---------------------------------------------------------------------------


class LLMFindingOutput(BaseModel):
    """Single finding as returned by the LLM, prior to assigning audit IDs."""

    category: str = Field(description="Finding category: overprivileged or dormant_privileged")
    severity: str = Field(description="Severity level: critical, high, medium, low")
    principal_id: str = Field(description="Object ID of the affected principal")
    principal_name: str = Field(description="Display name of the affected principal")
    principal_type: str = Field(description="Type: Member, Guest, or ServicePrincipal")
    role_assignments: list[dict[str, Any]] = Field(description="List of relevant role assignments")
    evidence: dict[str, Any] = Field(description="Supporting evidence, e.g. days_since_last_sign_in")
    remediation: str = Field(description="Recommended remediation action")
    narrative: str = Field(description="Plain-language explanation of the risk")


class FindingsList(BaseModel):
    """Wrapper for a list of findings parsed from LLM output."""

    findings: list[LLMFindingOutput]


class LLMQueryResponse(BaseModel):
    """Structured response from the LLM for a natural-language query."""

    structured_data: list[dict[str, Any]] = Field(
        description="Array of matching records or computed values"
    )
    natural_language_summary: str = Field(
        description="Human-readable summary of the answer"
    )
    answerable: bool = Field(default=True, description="Whether the question could be answered")


# ---------------------------------------------------------------------------
# Concrete provider
# ---------------------------------------------------------------------------


class OpenAIProvider(BaseLLMProvider):
    """LLM provider using OpenAI via LangChain's ChatOpenAI.

    Retry behaviour
    ---------------
    ``ChatOpenAI`` is initialised with ``max_retries=3``, which triggers
    exponential backoff (base delay ~1 s, doubling each attempt).  This
    satisfies the PRD requirement of 3 attempts with exponential backoff
    without introducing an extra dependency.

    Prompt templates
    ----------------
    Inline templates are defined as class constants.  Future sub-tasks
    (4.4) will factor them into version-controlled text files under
    ``app/llm/prompts/``.
    """

    # ------------------------------------------------------------------
    # Prompt templates (inline — to be moved to separate files in sub-task 4.4)
    # ------------------------------------------------------------------

    OVERPRIVILEGED_SYSTEM_PROMPT = (
        "You are an Azure AD RBAC audit analyst.  "
        "Analyse the following pre-processed privilege data and identify "
        "accounts that are **overprivileged** — i.e. the assigned roles "
        "grant substantially more permission than the user's sign-in "
        "activity and usage patterns suggest they need.  "
        "Consider role tier (Tier 0 Global Admin > Tier 1 > Tier 2), "
        "assignment type (direct vs. group-inherited), and activity signals.\n\n"
        "Return a JSON object with a single key 'findings' containing an array of objects. "
        "Each object must have these fields:\n"
        "- category (string): 'overprivileged'\n"
        "- severity (string): 'critical', 'high', 'medium', or 'low'\n"
        "- principal_id (string): the user/service principal object ID\n"
        "- principal_name (string): display name\n"
        "- principal_type (string): 'Member', 'Guest', or 'ServicePrincipal'\n"
        "- role_assignments (array of objects): each with role_name and assignment_type\n"
        "- evidence (object): include days_since_last_sign_in, role_tier, assignment_type, privileged_role_count\n"
        "- remediation (string): actionable recommendation\n"
        "- narrative (string): 2-4 sentence explanation of why this is a risk\n"
        "If no overprivileged accounts are found, return an empty array."
    )

    DORMANT_SYSTEM_PROMPT = (
        "You are an Azure AD RBAC audit analyst.  "
        "Analyse the following pre-processed privilege data and identify "
        "**dormant privileged role assignments** — role assignments to "
        "principals who have not signed in or exercised the role's "
        "capabilities within the configured dormancy threshold (default 30 days).\n\n"
        f"Dormancy threshold: {get_settings().dormant_threshold_days} days.\n\n"
        "Return a JSON object with a single key 'findings' containing an array of objects. "
        "Each object must have these fields:\n"
        "- category (string): 'dormant_privileged'\n"
        "- severity (string): 'critical', 'high', 'medium', or 'low'\n"
        "- principal_id (string): the user/service principal object ID\n"
        "- principal_name (string): display name\n"
        "- principal_type (string): 'Member', 'Guest', or 'ServicePrincipal'\n"
        "- role_assignments (array of objects): each with role_name and assignment_type\n"
        "- evidence (object): include days_since_last_sign_in, role_tier, assignment_type\n"
        "- remediation (string): actionable recommendation\n"
        "- narrative (string): 2-4 sentence explanation of why this is a risk\n"
        "If no dormant privileged accounts are found, return an empty array."
    )

    QUERY_SYSTEM_PROMPT = (
        "You are an Azure AD RBAC audit assistant.  "
        "Given the following context about a tenant's role assignments, "
        "users, and audit findings, answer the user's natural-language question.\n\n"
        "Rules:\n"
        "1. If the question cannot be answered from the provided context, set "answerable" to false.\n"
        "2. Otherwise, set "answerable" to true and provide:\n"
        "   - structured_data: an array of matching records or computed values\n"
        "   - natural_language_summary: a clear, concise answer\n"
        "Return a JSON object with keys: structured_data, natural_language_summary, answerable."
    )

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.openai_api_key:
            raise ValueError(
                "OpenAI API key not configured. Set the OPENAI_API_KEY environment variable."
            )

        model = getattr(settings, "openai_model", "gpt-4o-mini")
        temperature = getattr(settings, "openai_temperature", 0.0)
        max_retries = getattr(settings, "openai_max_retries", 3)

        self._llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=settings.openai_api_key,
            max_retries=max_retries,
            timeout=60,
        )
        self._findings_parser = PydanticOutputParser(pydantic_object=FindingsList)
        self._query_parser = PydanticOutputParser(pydantic_object=LLMQueryResponse)

        logger.info(
            "OpenAIProvider initialised (model=%s, max_retries=%d)",
            model,
            max_retries,
        )

    # ------------------------------------------------------------------
    # analyze_findings
    # ------------------------------------------------------------------

    def analyze_findings(self, preprocessed_data: dict) -> list[FindingSchema]:
        """Analyse preprocessed data and return findings for both categories.

        This implementation runs two separate LLM calls (one for overprivileged,
        one for dormant) and combines the results.  Each call uses the same
        preprocessed input but a different system prompt.
        """
        # Convert preprocessed_data to a string representation for the prompt.
        # A more robust implementation would serialize to JSON but for Phase 1
        # a concise summary is adequate.
        data_summary = self._summarise_preprocessed_data(preprocessed_data)

        all_findings: list[FindingSchema] = []

        # --- Overprivileged pass ---
        try:
            over_findings = self._call_with_parser(
                system_prompt=self.OVERPRIVILEGED_SYSTEM_PROMPT,
                data_summary=data_summary,
                category_label="overprivileged",
            )
            all_findings.extend(over_findings)
        except Exception:
            logger.exception("Overprivileged LLM analysis failed")
            # Continue with dormant analysis; do not abort the entire audit.

        # --- Dormant pass ---
        try:
            dormant_findings = self._call_with_parser(
                system_prompt=self.DORMANT_SYSTEM_PROMPT,
                data_summary=data_summary,
                category_label="dormant_privileged",
            )
            all_findings.extend(dormant_findings)
        except Exception:
            logger.exception("Dormant privileged LLM analysis failed")

        return all_findings

    def _call_with_parser(
        self,
        system_prompt: str,
        data_summary: str,
        category_label: str,
    ) -> list[FindingSchema]:
        """Invoke the LLM with the given prompt and parse the output into FindingSchema."""
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "Pre-processed data:\n{data}"),
        ])
        chain = prompt | self._llm | self._findings_parser

        result: FindingsList = chain.invoke({"data": data_summary})
        findings: list[LLMFindingOutput] = result.findings

        # Convert to FindingSchema with generated UUIDs and timestamps.
        now = datetime.now(timezone.utc)
        converted: list[FindingSchema] = []
        for f in findings:
            # Ensure the category matches what we expect (the LLM might get it wrong).
            # We trust the LLM for now; prompt enforcement should keep it correct.
            converted.append(
                FindingSchema(
                    id=uuid.uuid4(),
                    audit_id=uuid.UUID(int=0),  # placeholder; pipeline will set
                    category=f.category,
                    severity=f.severity,
                    principal_id=f.principal_id,
                    principal_name=f.principal_name,
                    principal_type=f.principal_type,
                    role_assignments=f.role_assignments,
                    evidence=f.evidence,
                    remediation=f.remediation,
                    narrative=f.narrative,
                    created_at=now,
                )
            )
        return converted

    # ------------------------------------------------------------------
    # answer_query
    # ------------------------------------------------------------------

    def answer_query(self, question: str, context: dict) -> QueryResponse:
        """Answer a natural-language question about a dataset or audit results."""
        prompt = ChatPromptTemplate.from_messages([
            ("system", self.QUERY_SYSTEM_PROMPT),
            (
                "human",
                "Context:\n{context}\n\nQuestion:\n{question}",
            ),
        ])
        chain = prompt | self._llm | self._query_parser

        context_str = self._serialise_context(context)

        try:
            result: LLMQueryResponse = chain.invoke({
                "context": context_str,
                "question": question,
            })
        except Exception:
            logger.exception("Query LLM call failed")
            return QueryResponse(
                question=question,
                structured_data=[],
                natural_language_summary=(
                    "I encountered an internal error while processing your question. "
                    "Please try again or rephrase your query."
                ),
                answerable=False,
            )

        return QueryResponse(
            question=question,
            structured_data=result.structured_data,
            natural_language_summary=result.natural_language_summary,
            answerable=result.answerable,
        )

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    @staticmethod
    def _summarise_preprocessed_data(data: dict) -> str:
        """Convert the preprocessed data dict to a concise string representation.

        The dict is expected to have keys like ``principal_id``, ``days_since_last_sign_in``,
        ``role_tier``, ``assignment_type``, ``privileged_role_count``, etc.  This
        method formats it as a readable summary to minimise token usage.
        """
        lines: list[str] = []
        for principal_id, details in data.items():
            lines.append(
                f"Principal {principal_id}:"
                f"  displayName={details.get('displayName', '?')},"
                f"  userType={details.get('userType', '?')},"
                f"  daysSinceLastSignIn={details.get('days_since_last_sign_in', 'N/A')},"
                f"  roleTier={details.get('role_tier', '?')},"
                f"  assignmentType={details.get('assignment_type', '?')},"
                f"  privilegedRoleCount={details.get('privileged_role_count', 0)},"
                f"  roles={details.get('roles', [])}"
            )
        return "\n".join(lines)

    @staticmethod
    def _serialise_context(context: dict) -> str:
        """Serialize the context dictionary into a string for the LLM prompt."""
        import json

        return json.dumps(context, indent=2, default=str)
