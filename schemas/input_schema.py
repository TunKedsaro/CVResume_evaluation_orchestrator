# -------------------------------------------------------------------
# schemas/input_schema.py
#
# WHAT THIS FILE IS FOR
# --------------------
# This module defines the **public request schema** for the
# CV Resume Evaluation Orchestrator API.
#
# It specifies the exact structure, types, and validation rules
# for incoming resume evaluation requests.
#
# KEY DESIGN DECISION
# -------------------
# This schema intentionally supports **both camelCase and snake_case**
# JSON field naming to maximize client compatibility.
#
# Example (both valid):
#   - snake_case: resume_json, target_role, output_lang
#   - camelCase:  resumeJson, targetRole, outputLang
#
# This is implemented via:
#   - alias=camelCase on each field
#   - populate_by_name=True in model_config
#
# This ensures:
# - Clean Python-native attribute access (snake_case internally)
# - Backward compatibility with existing clients
# - Frontend-friendly camelCase JSON
#
# ROLE-AWARE VS ROLE-AGNOSTIC EVALUATION
# -------------------------------------
# - resume_json is REQUIRED
# - target_role is OPTIONAL
#     - If provided: role-aware evaluation (role lookup + enrichment)
#     - If omitted: role-agnostic evaluation (generic scoring)
#
# WHAT THIS FILE IS NOT FOR
# ------------------------
# This module does NOT:
# - Perform business logic
# - Call downstream services
# - Normalize response payloads
# - Handle API routing or HTTP concerns
#
# It strictly defines **input validation and typing**.
#
# Any breaking change here is a **public API change** and must be
# versioned or explicitly documented.
# -------------------------------------------------------------------

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ResumeEvaluationRequest(BaseModel):
    """
    Request payload for resume evaluation.

    Supports both snake_case and camelCase JSON field names.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "resumeJson": {
                    "profile": {
                        "title": "AI Engineer",
                        "yearsExperience": 6
                    },
                    "summary": [
                        "AI/ML engineer with experience in production systems."
                    ],
                    "skills": {
                        "skills": ["Python", "LLMs", "GCP"]
                    }
                },
                # "targetRole": "NA",
                "outputLang": "en"
            }
        },
    )

    resume_json: Dict[str, Any] = Field(
        ...,
        alias="resumeJson",
        description="Structured resume JSON (non-null object)",
    )

    target_role: Optional[str] = Field(
        None,
        alias="targetRole",
        min_length=1,
        description=(
            "Optional role taxonomy ID. "
            "If provided, the orchestrator performs role-aware evaluation "
            "(role lookup + context enrichment). "
            "If omitted, evaluation is role-agnostic."
        ),
    )

    output_lang: Optional[Literal["en", "th"]] = Field(
        "en",
        alias="outputLang",
        description="Output language for feedback text",
    )

