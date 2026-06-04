from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas.finding import FindingSchema
from app.schemas.query import QueryResponse


class BaseLLMProvider(ABC):
    """Abstract interface for LLM-based analysis and query answering.

    All concrete providers (e.g. OpenAI, Azure OpenAI) must implement
    ``analyze_findings`` and ``answer_query``.  The methods return
    structured Pydantic models so that the downstream pipeline can
    rely on a consistent output format regardless of the underlying
    LLM backend.
    """

    @abstractmethod
    def analyze_findings(self, preprocessed_data: dict) -> list[FindingSchema]:
        """Analyse preprocessed role-assignment data and return findings.

        Parameters
        ----------
        preprocessed_data:
            Dictionary of computed features per principal, as produced
            by ``app.services.preprocessor``.  Expected keys include
            ``principal_id``, ``days_since_last_sign_in``, ``role_tier``,
            ``assignment_type``, and ``privileged_role_count``.

        Returns
        -------
        list[FindingSchema]
            Zero or more findings describing overprivileged or dormant
            privileged role assignments.
        """
        ...

    @abstractmethod
    def answer_query(self, question: str, context: dict) -> QueryResponse:
        """Answer a natural-language question about a dataset or its audit findings.

        Parameters
        ----------
        question:
            The user's natural-language question.
        context:
            Dictionary with relevant dataset and/or audit context; at
            minimum should contain ``dataset`` and optionally ``findings``.

        Returns
        -------
        QueryResponse
            Structured response with a machine-readable payload and a
            human-readable summary.  If unanswerable, ``answerable``
            is ``False`` and the summary explains the limitation.
        """
        ...
