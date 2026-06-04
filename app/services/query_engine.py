from __future__ import annotations

import logging

from app.llm.base import BaseLLMProvider
from app.schemas.query import QueryResponse

logger = logging.getLogger(__name__)


class QueryEngine:
    """Engine for answering natural-language questions about an RBAC dataset.

    The engine takes a preprocessed list of principals (with derived features
    such as days since last sign-in, role tier, assignment type, etc.) and a
    configured :class:`BaseLLMProvider`, then delegates the question to the
    LLM with a structured context.

    Usage
    -----
    .. code-block:: python

        from app.services.query_engine import QueryEngine
        from app.llm import get_llm_provider

        provider = get_llm_provider()
        engine = QueryEngine(provider)
        response = engine.answer(
            question="Show users with Global Admin who haven't signed in for 30 days.",
            dataset_name="My Tenant",
            dataset_id="some-uuid",
            preprocessed_principals=[
                {"principal_id": "...", "displayName": "...", ...}
            ],
        )
    """

    def __init__(self, provider: BaseLLMProvider) -> None:
        self._provider = provider

    def answer(
        self,
        question: str,
        dataset_name: str,
        dataset_id: str,
        preprocessed_principals: list[dict],
    ) -> QueryResponse:
        """Answer a natural-language question about the dataset.

        Parameters
        ----------
        question:
            The user's question (e.g., "Which groups grant Privileged Role Administrator?").
        dataset_name:
            Human-readable name of the dataset being queried.
        dataset_id:
            UUID string identifying the dataset.
        preprocessed_principals:
            A list of dictionaries, each representing one principal with derived
            features. Expected keys include:
            - principal_id
            - displayName
            - userType
            - days_since_last_sign_in
            - role_tier
            - assignment_type
            - privileged_role_count
            - roles (list of role names)

        Returns
        -------
        QueryResponse
            Structured answer with a machine-readable payload and a
            plain-language summary. If the question cannot be answered,
            ``answerable`` is ``False``.
        """
        context: dict = {
            "dataset_id": dataset_id,
            "dataset_name": dataset_name,
            "preprocessed_principals": preprocessed_principals,
        }

        logger.info(
            "QueryEngine: answering question for dataset '%s' (first 80 chars: %s)",
            dataset_name,
            question[:80],
        )

        return self._provider.answer_query(question, context)
