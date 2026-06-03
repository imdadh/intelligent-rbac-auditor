"""Pydantic request/response schemas for API validation and serialisation.

This package contains two categories of schema:

1. **API schemas** — request bodies and response envelopes used by the
   FastAPI route handlers (``dataset.py``, ``audit.py``, ``finding.py``,
   ``query.py``, ``common.py``).

2. **Dataset domain schemas** — the canonical definition of the synthetic
   Azure AD tenant snapshot format (``dataset_schema.py``).  These are
   used both for validating ingested payloads and as the authoritative
   reference for the synthetic data generator.
"""
