# -------------------------------------------------------------------
# schemas/output_schema.py
#
# WHAT THIS FILE IS FOR
# --------------------
# This module defines the **internal response schemas** used by the
# CV Resume Evaluation Orchestrator API.
#
# These schemas represent the *canonical Python-side structure*
# of successful evaluation responses BEFORE they are serialized
# and returned to clients.
#
# NAMING CONVENTION (IMPORTANT)
# -----------------------------
# All fields in this file use **snake_case** by design.
#
# At the API boundary (in api.py), response objects are converted to
# **camelCase JSON** using:
#     convert_keys_snake_to_camel()
#
# This separation ensures:
# - Pythonic naming internally
# - Frontend-friendly camelCase externally
# - A single, explicit transformation point
#
# DO NOT rename fields here to camelCase.
# Doing so will break consistency and double-conversion logic.
#
# WHAT THIS FILE IS NOT FOR
# ------------------------
# This module does NOT:
# - Perform JSON key conversion
# - Contain HTTP or FastAPI logic
# - Include business rules
# - Handle error responses
#
# It strictly defines **typed response data structures**.
#
# Any change here impacts the public API contract and must be
# carefully reviewed and documented.
# -------------------------------------------------------------------

from __future__ import annotations

from typing import Any, Dict, Optional, Literal
from pydantic import BaseModel, Field


class EvaluationConclusion(BaseModel):
    """
    Aggregated evaluation outcome.

    Contains the final resume score and per-section contribution
    used to compute the overall result.
    """

    final_resume_score: float = Field(..., ge=0, le=100)
    section_contribution: Dict[str, Any] = Field(default_factory=dict)


class ResumeEvaluationResponse(BaseModel):
    """
    Core evaluation payload returned on success.
    """

    conclusion: EvaluationConclusion
    section_detail: Dict[str, Any] = Field(default_factory=dict)


class OrchestratorEnvelope(BaseModel):
    """
    Standard response envelope for the orchestrator.

    NOTE:
    - This schema is INTERNAL and uses snake_case.
    - Keys are converted to camelCase at the API boundary
      using convert_keys_snake_to_camel().
    """

    model_config = {"extra": "forbid"}

    # Contract:
    #   HTTP < 400  -> status = "success"
    #   HTTP >= 400 -> status = "error"
    #
    # Default is "success" to avoid regressions if not explicitly set.
    status: Literal["success", "error"] = "success"

    # Success responses include data; Optional allows future reuse
    # of this envelope for error-only responses if needed.
    data: Optional[ResumeEvaluationResponse] = None

    # Always injected by middleware / api.py
    correlation_id: Optional[str] = None

    # Debug-only metadata (e.g., preserved upstream status)
    metadata: Optional[Dict[str, Any]] = None
