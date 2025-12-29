"""
functions/orchestrator/data_fetcher.py

WHAT THIS FILE IS FOR
---------------------
This module provides a domain-aware, asynchronous data access layer
for retrieving structured data from internal services, primarily
`eport_data_api`.

It exists to:
- Centralize all Data API access logic in one place
- Read endpoint templates from parameters/config.yaml
- Perform async HTTP GET requests with retries
- Add structured logging for observability
- Normalize common response wrappers (e.g. {"data": {...}})
- Shield orchestrator business logic from HTTP and schema details

This class represents a *data access boundary* for the orchestrator.

WHAT THIS FILE IS NOT FOR
-------------------------
This module is NOT responsible for:
- Calling external / third-party services
- Performing POST or long-running evaluation calls
- Business logic, scoring, or orchestration decisions
- Payload construction for downstream AI/LLM services
- Synchronous request handling

Those concerns belong to higher-level services
(e.g. ResumeEvaluationService, API route handlers).

RELATIONSHIP TO http_client.py
------------------------------
- data_fetcher.py:
    * Asynchronous (httpx.AsyncClient)
    * Domain-aware (Data API only)
    * Uses config-driven endpoint templates
    * Includes retries, logging, and response normalization
    * Intended for frequent, structured GET calls

- http_client.py:
    * Synchronous (requests)
    * Generic transport utility
    * No retries or logging
    * Used for long-running POST calls (e.g. resume evaluation / LLM calls)

They intentionally coexist and serve different access patterns.

CONFIGURATION
-------------
- Endpoint paths are defined in: parameters/config.yaml
- Base URL, timeouts, and retry counts come from Settings
- Endpoint templates are cached at startup for efficiency

DESIGN INTENT
-------------
This module acts as a *thin but opinionated data access layer*.
If new Data API endpoints are added, they should be implemented here
as explicit methods rather than accessed ad-hoc elsewhere.

Any expansion (e.g. caching, circuit breakers, tracing propagation)
should be added deliberately here, not in API handlers.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx
import structlog
import yaml

from functions.utils.settings import Settings

logger = structlog.get_logger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[2] / "parameters" / "config.yaml"


@lru_cache(maxsize=1)
def load_orchestrator_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        logger.warning("orchestrator_config_missing", path=str(CONFIG_PATH))
        return {}

    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            logger.warning("orchestrator_config_not_dict", path=str(CONFIG_PATH))
            return {}
        logger.info("orchestrator_config_loaded", path=str(CONFIG_PATH))
        return data
    except Exception as exc:  # noqa: BLE001
        logger.error("orchestrator_config_load_error", path=str(CONFIG_PATH), error=str(exc))
        return {}


class DataFetcher:
    """
    Thin async client around eport_data_api.

    - Reads endpoint templates from parameters/config.yaml
    - Adds retry and basic logging
    - Normalizes common response wrappers (e.g. {"data": {...}})
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._base_url = str(settings.data_api_base_url).rstrip("/")
        self._config = load_orchestrator_config()
        self._timeout = settings.http_timeout_seconds
        self._max_retries = settings.max_retries

    async def fetch_role_core(self, role_id: str) -> Dict[str, Any]:
        """
        Fetch role core info by role_id.

        IMPORTANT:
        - role_id may contain reserved characters like '#', so we URL-encode it
          before formatting into the path.
        - Data API may return wrappers like {"data": {...}}; we normalize and
          return the inner dict when appropriate.
        """
        template = self._get_endpoint_template(section="data_api", key="role_core")

        role_id_encoded = quote(role_id, safe="")  # role#ai_engineer -> role%23ai_engineer
        path = template.format(role_id=role_id_encoded)

        raw = await self._get_json(path, context={"role_id": role_id})

        # Normalize common wrappers so downstream code doesn't guess structure.
        # If it's {"data": {...}} return the inner dict; otherwise return raw.
        if isinstance(raw, dict):
            inner = raw.get("data")
            if isinstance(inner, dict):
                return inner

        return raw

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _get_endpoint_template(self, section: str, key: str) -> str:
        """
        Read an endpoint path template from the loaded config.

        Example:
            section="data_api", key="role_core"
            → "/v1/roles/{role_id}/core"
        """
        try:
            template = self._config[section]["endpoints"][key]
            if not isinstance(template, str) or not template.startswith("/"):
                raise TypeError("Endpoint template must be a string starting with '/'")
            return template
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "endpoint_template_missing_or_invalid",
                section=section,
                key=key,
                error=str(exc),
            )
            raise RuntimeError(f"Missing or invalid endpoint template for {section}.{key}") from exc

    async def _get_json(
        self,
        path: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Perform a GET request and return JSON dict.

        - Retries: max_retries=2 => attempts=3
        - Raises: httpx.HTTPStatusError / httpx.RequestError if exhausted
        """
        url = self._base_url + path
        ctx = context or {}
        last_exc: Exception | None = None

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for attempt in range(1, self._max_retries + 2):
                try:
                    resp = await client.get(url)

                    # If non-2xx, capture short response to help debugging
                    if resp.status_code >= 400:
                        snippet = (resp.text or "")[:500]
                        logger.warning(
                            "data_fetch_http_error",
                            url=url,
                            attempt=attempt,
                            status_code=resp.status_code,
                            response_snippet=snippet,
                            **ctx,
                        )
                        resp.raise_for_status()

                    data = resp.json()
                    logger.info("data_fetch_success", url=url, attempt=attempt, **ctx)
                    if isinstance(data, dict):
                        return data
                    # Force dict return type for callers
                    return {"data": data}

                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    logger.warning(
                        "data_fetch_attempt_failed",
                        url=url,
                        attempt=attempt,
                        max_retries=self._max_retries,
                        error=str(exc),
                        **ctx,
                    )
                    if attempt >= self._max_retries + 1:
                        logger.error(
                            "data_fetch_exhausted_retries",
                            url=url,
                            attempts=attempt,
                            error=str(exc),
                            **ctx,
                        )
                        raise

        assert last_exc is not None
        raise last_exc
