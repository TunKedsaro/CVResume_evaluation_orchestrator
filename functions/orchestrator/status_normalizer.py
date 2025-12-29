"""
functions/orchestrator/status_normalizer.py

WHAT THIS FILE IS FOR
---------------------
This module defines the *single canonical rule* for mapping
internal / upstream execution statuses into the public
orchestrator response contract.

It is responsible for:
- Translating HTTP-level outcomes into a stable API `status` value
- Decoupling public API semantics from upstream evaluator statuses
- Preserving upstream status values strictly for debugging/metadata

PUBLIC CONTRACT RULE
--------------------
The orchestrator exposes a **binary, stable status model**:

- HTTP status < 400  -> status = "success"
- HTTP status >= 400 -> status = "error"

This ensures:
- Consistent semantics across all endpoints
- No leakage of internal evaluator state machines
- Predictable behavior for frontend and downstream consumers

UPSTREAM STATUS HANDLING
------------------------
- `upstream_status` may be any string returned by a downstream service
  (e.g. "completed", "failed", "timeout", None)
- It is NEVER exposed as the public API status
- It MAY be included in `metadata.originalStatus` for debugging purposes
  when debug metadata is enabled

WHAT THIS FILE IS NOT FOR
-------------------------
This module MUST NOT:
- Inspect evaluator payloads
- Infer business logic outcomes
- Decide HTTP status codes
- Log, raise, or handle exceptions

It performs **pure, deterministic mapping only**.

DESIGN INTENT
-------------
- Keep public API semantics simple and future-proof
- Prevent accidental contract drift from upstream changes
- Centralize status logic in one place to avoid duplication

Any change to status semantics MUST be done here and reflected
in the API specification and tests.
"""

from __future__ import annotations
from typing import Optional, Tuple


def normalize_orchestrator_status(
    *,
    http_status: int,
    upstream_status: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """
    Orchestrator contract:
      - HTTP < 400  -> status = "success"
      - HTTP >= 400 -> status = "error"

    upstream_status (e.g. "completed") is preserved for debugging only.
    """
    if http_status < 400:
        return "success", upstream_status
    return "error", upstream_status
