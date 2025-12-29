"""
functions/utils/http_client.py

WHAT THIS FILE IS FOR
---------------------
This module provides a minimal, synchronous HTTP client abstraction
used by the orchestrator layer to make outbound HTTP calls to
downstream services.

It exists to:
- Centralize basic HTTP call behavior (currently POST + JSON)
- Standardize timeout handling
- Avoid scattering raw `requests.post(...)` calls across the codebase

This client is intentionally kept *very thin*.

WHAT THIS FILE IS NOT FOR
-------------------------
This module is NOT responsible for:
- Retry logic
- Logging or structured tracing
- Endpoint discovery or URL templating
- Response normalization or schema validation
- Business logic or error translation

Those responsibilities belong to higher-level components
(e.g. ResumeEvaluationService, DataFetcher, API handlers).

RELATIONSHIP TO data_fetcher.py
-------------------------------
- http_client.py:
    * Synchronous
    * Generic
    * Transport-only
    * Used for long-running POST calls (e.g. LLM evaluation)

- data_fetcher.py:
    * Asynchronous (httpx)
    * Domain-aware (Data API)
    * Includes retries, logging, and response normalization
    * Used for structured GET calls to internal services

Both exist intentionally and serve different purposes.

DESIGN INTENT
-------------
This file acts as a *low-level transport utility*.
If additional behavior is needed (retries, circuit breakers,
metrics, async support), it should be added either:
- in a higher-level service, or
- via a new, explicit client abstraction (not by bloating this one).
"""

from __future__ import annotations

import requests
from typing import Any, Dict, Optional, Tuple, Union

# Timeout can be:
# - single float -> applied to both connect + read
# - (connect_timeout, read_timeout)
TimeoutType = Union[float, Tuple[float, float]]


class HttpClient:
    """
    Minimal synchronous HTTP client wrapper.

    PURPOSE
    -------
    This class provides a *very thin abstraction* over `requests`
    to standardize HTTP calls across the orchestrator layer.

    It intentionally:
    - Does NOT add retries
    - Does NOT add logging
    - Does NOT interpret response payloads
    - Does NOT enforce schemas

    Those responsibilities belong to higher-level services
    (e.g. ResumeEvaluationService, DataFetcher).

    CURRENT USAGE
    -------------
    - Used by ResumeEvaluationService to call the downstream
      CV Resume Evaluation service (POST, long-running LLM call).
    - Designed for synchronous usage only.

    TIMEOUT SEMANTICS
    -----------------
    `timeout_seconds` is passed directly to `requests.post`.

    This means:
    - If a single float is provided → used for both connect + read
    - If a tuple (connect, read) is provided → split behavior

    IMPORTANT:
    Long-running LLM evaluations SHOULD use a larger read timeout
    than connect timeout. This class supports that via tuple input,
    but does not enforce it by default.
    """

    def __init__(self, timeout_seconds: TimeoutType = 60):
        """
        Initialize the HTTP client.

        Args:
            timeout_seconds:
                Either:
                - float: total timeout (connect + read)
                - (connect_timeout, read_timeout)

                Default is 60 seconds total.

        NOTE:
        This value is stored and reused for every request
        unless overridden at call-time.
        """
        self.timeout_seconds = timeout_seconds

    def post_json(
        self,
        url: str,
        json_body: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        timeout_seconds: Optional[TimeoutType] = None,
    ) -> requests.Response:
        """
        Send a POST request with a JSON body.

        This is a thin pass-through to `requests.post`.

        Args:
            url:
                Full URL of the downstream endpoint.
            json_body:
                JSON-serializable request body.
            headers:
                Optional HTTP headers (e.g. Content-Type, Correlation-Id).
            timeout_seconds:
                Optional override for timeout behavior for this call only.
                If not provided, falls back to the instance default.

        Returns:
            requests.Response

        Raises:
            requests.RequestException:
                Any network-level error (timeout, DNS, connection error).
                Caller is responsible for catching and translating this
                into domain-specific errors.
        """
        return requests.post(
            url,
            json=json_body,
            headers=headers or {},
            timeout=timeout_seconds if timeout_seconds is not None else self.timeout_seconds,
        )
