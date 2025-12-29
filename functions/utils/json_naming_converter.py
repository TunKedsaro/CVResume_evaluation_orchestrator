"""
functions/utils/json_naming_converter.py

WHAT THIS FILE IS FOR
---------------------
This module provides a **recursive JSON key normalization utility**
used by the CV Resume Evaluation Orchestrator to enforce a
**stable camelCase response contract**, regardless of upstream or
internal naming conventions.

It converts dictionary keys from snake_case → camelCase while
preserving values and structure.

This is primarily used:
- Right before returning API responses
- To normalize evaluator / legacy payloads
- To ensure frontend-facing contracts remain consistent

CORE FUNCTIONALITY
------------------
- Convert snake_case keys to camelCase
- Recursively traverse nested dicts and lists
- Preserve non-dict primitives unchanged
- Avoid mutating the original input object

PRESERVE-CONTAINER MECHANISM
----------------------------
Some response fields are *free-form containers* whose **inner keys**
must remain unchanged (e.g. dynamic section IDs, rubric names).

This module supports this via `preserve_container_keys`:

- The container key itself is normalized to camelCase
- BUT its child dictionary keys are preserved exactly as-is

Example:
    preserve_container_keys = {"scores"}

Input:
    {
        "section_detail": {
            "Profile": {
                "scores": {
                    "ContentQuality": {...}
                }
            }
        }
    }

Output:
    {
        "sectionDetail": {
            "Profile": {
                "scores": {
                    "ContentQuality": {...}   # preserved
                }
            }
        }
    }

DESIGN CONSTRAINTS
------------------
- Safe to call on any JSON-like object
- No assumptions about schema shape
- Works with mixed snake_case / camelCase input
- Deterministic and side-effect free

WHAT THIS FILE IS NOT FOR
-------------------------
This module MUST NOT:
- Perform request validation
- Modify values or business semantics
- Enforce schema correctness
- Perform I/O or logging
- Apply domain-specific rules

It is a **pure transformation utility**.

DESIGN INTENT
-------------
- Isolate naming normalization from business logic
- Prevent frontend contract drift
- Allow upstream services to evolve independently
- Make response normalization explicit and auditable

Any changes to response naming conventions should be implemented
here and tested via integration tests, not scattered across handlers.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional


_SNAKE_RE = re.compile(r"_([a-zA-Z0-9])")


def snake_to_camel(s: str) -> str:
    """
    Convert snake_case string to camelCase.

    - Leaves strings without '_' unchanged
    - Preserves leading/trailing underscores
    """
    if "_" not in s:
        return s

    # preserve leading/trailing underscores
    leading = len(s) - len(s.lstrip("_"))
    trailing = len(s) - len(s.rstrip("_"))
    core = s.strip("_")

    if not core:
        return s  # e.g. "___"

    parts = [p for p in core.split("_") if p]
    if not parts:
        return s

    first = parts[0]
    rest = [p[:1].upper() + p[1:] if p else p for p in parts[1:]]
    camel = first + "".join(rest)

    return ("_" * leading) + camel + ("_" * trailing)


def convert_keys_snake_to_camel(
    obj: Any,
    *,
    preserve_container_keys: Optional[Iterable[str]] = None,
) -> Any:
    """
    Recursively convert dict keys from snake_case to camelCase.

    IMPORTANT:
    Some fields (e.g. userOrLlmComments, userInputCvTextBySection) are
    *free-form containers* whose INNER KEYS must remain unchanged
    (e.g. section IDs like "profile_summary").

    Args:
        obj:
            Any JSON-like object (dict / list / primitive)
        preserve_container_keys:
            Iterable of keys (snake_case OR camelCase) for which:
            - the container key is converted to camelCase
            - BUT its *child dict keys are preserved exactly*

    Returns:
        New object with converted keys (input is not mutated)
    """
    preserve = set(preserve_container_keys or [])

    # ---------- list ----------
    if isinstance(obj, list):
        return [
            convert_keys_snake_to_camel(
                x, preserve_container_keys=preserve
            )
            for x in obj
        ]

    # ---------- dict ----------
    if isinstance(obj, dict):
        out: dict[str, Any] = {}

        for key, value in obj.items():
            if not isinstance(key, str):
                out[key] = value
                continue

            camel_key = snake_to_camel(key)

            # match both snake_case and camelCase
            preserve_children = key in preserve or camel_key in preserve

            if preserve_children and isinstance(value, dict):
                # convert ONLY the container key; keep inner keys unchanged
                out[camel_key] = value
            else:
                out[camel_key] = convert_keys_snake_to_camel(
                    value, preserve_container_keys=preserve
                )

        return out

    # ---------- primitive ----------
    return obj
