"""
functions/orchestrator/resume_evaluation_service.py

WHAT THIS FILE IS FOR
---------------------
This module defines a *thin, synchronous client* for calling the downstream
CV Resume Evaluation Service (LLM-based evaluator).

It is responsible for:
- Constructing the evaluator request payload
- Injecting optional role_context into the evaluator prompt
- Propagating correlation IDs downstream
- Applying evaluator-specific timeout settings
- Validating HTTP and JSON responses
- Normalizing evaluator output into a stable internal structure
  consumable by the orchestrator layer

CALL FLOW CONTEXT
-----------------
FastAPI (api.py)
  → ResumeEvaluationService.evaluate()
      → POST /evaluation/final-resume-score-async
          (downstream evaluator service)

This service is *not* exposed publicly and MUST NOT leak downstream
implementation details directly to API consumers.

REQUEST BEHAVIOR
----------------
- `resume_json` is passed through as-is (already validated upstream)
- `target_role` is OPTIONAL:
    - if provided: a resolved, human-readable role name
    - if omitted: downstream runs role-agnostic evaluation
- `role_context` is injected ONLY when provided
- `output_lang` defaults to "en"
- `X-Correlation-Id` is always forwarded downstream

ERROR HANDLING RULES
--------------------
- Non-JSON evaluator responses → RuntimeError
- HTTP status >= 400 from evaluator → RuntimeError
- No retries are performed here (retry policy is enforced upstream)

This allows the orchestrator to:
- Map failures to HTTP 502
- Apply a consistent error envelope

RESPONSE NORMALIZATION
----------------------
Evaluator responses are normalized to a predictable internal structure:

- Handles legacy typo: "conclution" → "conclusion"
- Extracts:
    - conclusion
    - section_detail
    - metadata
    - response_time
    - estimated_cost_thd
- Attaches correlation_id for traceability

Returned keys are still snake_case internally;
final camelCase conversion is handled at the API boundary.

WHAT THIS FILE IS NOT FOR
-------------------------
This module MUST NOT:
- Perform HTTP routing
- Apply API response envelopes
- Normalize public-facing JSON naming
- Implement business rules or scoring logic
- Log request/response bodies

DESIGN INTENT
-------------
- Keep evaluator integration isolated and replaceable
- Minimize assumptions about evaluator internals
- Provide a stable adapter layer between orchestrator and LLM service

Any change to evaluator endpoints, payloads, or response formats
should be handled here without impacting API contracts.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from functions.utils.http_client import HttpClient
from functions.utils.settings import Settings


class ResumeEvaluationService:
    """
    Thin client for the CV Resume Evaluation Service.

    Responsibilities:
    - Construct evaluator payload
    - Pass role_context as additional prompt context (if provided)
    - Handle HTTP + JSON errors safely
    - Normalize evaluator response structure
    """

    def __init__(self, settings: Settings):
        if not settings.evaluation_api_base_url:
            raise ValueError("evaluation_api_base_url is required")

        self.settings = settings

        # Evaluator calls can be slow; use dedicated timeout (not the generic HTTP timeout)
        timeout = getattr(settings, "evaluation_timeout_seconds", None) or settings.http_timeout_seconds
        self.http = HttpClient(timeout_seconds=timeout)

    def evaluate(
        self,
        *,
        resume_json: Dict[str, Any],
        target_role: Optional[str] = None,
        role_context: Optional[str] = None,
        output_lang: str = "en",
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        correlation_id = correlation_id or str(uuid.uuid4())

        url = f"{self.settings.evaluation_api_base_url}/evaluation/final-resume-score-async"

        # ------------------------------------------------------------------
        # Build evaluator payload
        # ------------------------------------------------------------------
        payload: Dict[str, Any] = {
            "resume_json": resume_json,
            "output_lang": output_lang,
        }

        # Include target_role ONLY if present (role-agnostic evaluation supported)
        if target_role:
            payload["target_role"] = target_role

        # Inject role_context ONLY if present (keeps evaluator backward compatible)
        if role_context:
            payload["role_context"] = role_context

        headers = {
            "Content-Type": "application/json",
            "X-Correlation-Id": correlation_id,
        }

        # ------------------------------------------------------------------
        # HTTP call
        # ------------------------------------------------------------------
        resp = self.http.post_json(url, payload, headers=headers)

        # ------------------------------------------------------------------
        # Response handling
        # ------------------------------------------------------------------
        try:
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(f"Evaluator returned non-JSON (status={resp.status_code})") from exc

        if resp.status_code >= 400:
            raise RuntimeError(f"Evaluator error (status={resp.status_code}): {data}")

        # ------------------------------------------------------------------
        # Normalize evaluator response
        # (handles legacy typo: 'conclution')
        # ------------------------------------------------------------------
        response_obj = data.get("response", {}) or {}

        conclusion = (
            response_obj.get("conclusion")
            or response_obj.get("Conclution")
            or response_obj.get("conclution")
            or {}
        )

        section_detail = (
            response_obj.get("section_detail")
            or response_obj.get("Section_detail")
            or {}
        )

        metadata = (
            response_obj.get("metadata")
            or response_obj.get("Metadata")
            or {}
        )

        normalized = {
            "conclusion": conclusion,
            "section_detail": section_detail,
            "metadata": metadata,
            "response_time": data.get("response_time"),
            "estimated_cost_thd": data.get("estimated_cost_thd"),
            "correlation_id": correlation_id,
        }
        return normalized
