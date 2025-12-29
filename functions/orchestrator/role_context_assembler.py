"""
functions/orchestrator/role_context_assembler.py

WHAT THIS FILE IS FOR
---------------------
This module constructs a *prompt-ready role context string* from a
Data API `role_core` payload.

It acts as an adapter between:
- Structured role metadata (often inconsistent across sources)
- A stable, human-readable text block suitable for LLM prompting

The output is intended to be injected into the downstream resume
evaluation prompt as additional role context.

RESPONSIBILITIES
----------------
- Extract role title and description defensively from multiple key variants
- Extract responsibilities from heterogeneous payload shapes
- Extract required skills with optional proficiency levels
- Deduplicate and normalize extracted text
- Produce a clean, predictable, LLM-friendly text format
- Return `None` when no meaningful role context can be constructed

ROLE CONTEXT FORMAT
-------------------
When present, the assembled role context follows this structure:

    Role: <role title>
    Description: <role description>
    Key responsibilities:
    - <responsibility 1>
    - <responsibility 2>
    Required skills:
    - <skill name> (<proficiency>)

Sections are included ONLY when data exists.
Formatting is intentionally simple and stable to avoid prompt noise.

DEFENSIVE EXTRACTION STRATEGY
-----------------------------
The Data API may return role metadata under multiple schemas and naming
conventions (snake_case, camelCase, nested, flattened).

This module:
- Checks multiple candidate keys for each semantic field
- Accepts both list- and string-based representations
- Handles list[dict], list[str], and scalar string cases
- Deduplicates responsibilities while preserving original order

FEATURE FLAG CONTEXT
--------------------
Usage of this module is controlled upstream via:

    settings.enable_role_with_skills_and_responsibilities_str

When disabled, role context is not generated or injected.

WHAT THIS FILE IS NOT FOR
-------------------------
This module MUST NOT:
- Call external services
- Perform HTTP requests
- Modify role_core payloads
- Apply business logic or scoring
- Decide whether role context should be enabled
- Log sensitive or large payloads

It is a pure transformation utility.

DESIGN INTENT
-------------
- Isolate role-context logic from the orchestrator flow
- Make prompt construction robust to schema drift
- Ensure LLM prompts remain readable, deterministic, and minimal
- Allow role metadata to evolve without breaking evaluation logic

Any changes to role context formatting or extraction rules
should be implemented here and validated with evaluator behavior.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional
import structlog

logger = structlog.get_logger(__name__)


class RoleContextAssembler:
    """
    Build a prompt-ready role context string from Data API role_core payload.

    Goals:
    - Always return a safe string (or None) even if fields are missing
    - Include responsibilities when available (optional)
    - Keep formatting stable and easy for LLM to consume
    """

    @staticmethod
    def build(role_core: dict[str, Any]) -> Optional[str]:
        if not isinstance(role_core, dict):
            return None

        role_obj = role_core.get("role") if isinstance(role_core.get("role"), dict) else {}

        role_title = (
            role_obj.get("role_title")
            or role_obj.get("roleTitle")
            or role_obj.get("title")
            or role_core.get("role_title")
            or role_core.get("roleTitle")
            or role_core.get("title")
            or role_core.get("role_name")
            or role_core.get("name")
        )

        role_description = (
            role_obj.get("role_description")
            or role_obj.get("roleDescription")
            or role_core.get("role_description")
            or role_core.get("roleDescription")
        )

        # -----------------------------
        # Responsibilities (optional)
        # -----------------------------
        responsibilities = RoleContextAssembler._extract_responsibilities(role_core, role_obj)

        # -----------------------------
        # Skills (optional)
        # -----------------------------
        required_skills = role_core.get("required_skills")
        skills_lines: list[str] = []
        if isinstance(required_skills, list):
            for item in required_skills:
                if not isinstance(item, dict):
                    continue
                name = (
                    item.get("role_required_skills_name")
                    or item.get("skill_name")
                    or item.get("name")
                    or item.get("skillName")
                )
                prof = (
                    item.get("role_required_skills_proficiency_lv")
                    or item.get("proficiency")
                    or item.get("skill_proficiency_lv")
                    or item.get("skillProficiencyLv")
                )

                if isinstance(name, str) and name.strip():
                    if isinstance(prof, str) and prof.strip():
                        skills_lines.append(f"- {name.strip()} ({prof.strip()})")
                    else:
                        skills_lines.append(f"- {name.strip()}")

        # If absolutely nothing meaningful exists, return None
        if not any(
            [
                isinstance(role_title, str) and role_title.strip(),
                isinstance(role_description, str) and role_description.strip(),
                len(responsibilities) > 0,
                len(skills_lines) > 0,
            ]
        ):
            return None

        # -----------------------------
        # Assemble role context
        # -----------------------------
        lines: list[str] = []
        if isinstance(role_title, str) and role_title.strip():
            lines.append(f"Role: {role_title.strip()}")

        if isinstance(role_description, str) and role_description.strip():
            lines.append(f"Description: {role_description.strip()}")

        if responsibilities:
            lines.append("Key responsibilities:")
            lines.extend([f"- {r}" for r in responsibilities])

        if skills_lines:
            lines.append("Required skills:")
            lines.extend(skills_lines)

        role_context = "\n".join(lines).strip()

        logger.debug(
            "role_context_built",
            role_title=(role_title.strip() if isinstance(role_title, str) else None),
            length=len(role_context),
            skill_count=len(skills_lines),
            responsibility_count=len(responsibilities),
        )

        return role_context or None

    @staticmethod
    def _extract_responsibilities(role_core: dict[str, Any], role_obj: dict[str, Any]) -> list[str]:
        """
        Defensive extraction: responsibilities can be stored in several shapes.
        Returns a cleaned list of bullet strings.
        """
        candidates: list[Any] = []

        # Most likely locations
        candidates.append(role_obj.get("role_responsibilities"))
        candidates.append(role_obj.get("roleResponsibilities"))
        candidates.append(role_core.get("role_responsibilities"))
        candidates.append(role_core.get("roleResponsibilities"))

        # Generic keys some APIs use
        candidates.append(role_obj.get("responsibilities"))
        candidates.append(role_core.get("responsibilities"))

        # Sometimes responsibilities come under "tasks"
        candidates.append(role_obj.get("tasks"))
        candidates.append(role_core.get("tasks"))

        out: list[str] = []

        def add_text(x: Any) -> None:
            if isinstance(x, str):
                s = x.strip()
                if s:
                    out.append(s)

        for c in candidates:
            if c is None:
                continue

            # Case 1: list[str]
            if isinstance(c, list):
                for item in c:
                    if isinstance(item, str):
                        add_text(item)
                    elif isinstance(item, dict):
                        # Case 2: list[dict] with common fields
                        add_text(item.get("responsibility"))
                        add_text(item.get("text"))
                        add_text(item.get("task"))
                        add_text(item.get("description"))
                continue

            # Case 3: single string
            if isinstance(c, str):
                add_text(c)
                continue

        # De-dup while preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for r in out:
            key = r.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(r)

        return deduped
