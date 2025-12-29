"""
functions/utils/settings.py

WHAT THIS FILE IS FOR
---------------------
This module defines the *single source of truth* for runtime configuration
of the CV Resume Evaluation Orchestrator API.

It is responsible for:
- Defining all supported configuration fields (via Pydantic BaseSettings)
- Loading default values from parameters/parameters.yaml
- Overriding defaults with environment variables (CVRESUME_ORCH_*)
- Validating required settings (e.g. service URLs)
- Exposing a cached, fully-validated Settings object to the application

This module ensures configuration is:
- Explicit
- Typed
- Validated
- Environment-aware
- Loaded exactly once per process

LOAD & PRECEDENCE MODEL
-----------------------
Configuration is loaded in the following order (last wins):

1) YAML defaults from:
       parameters/parameters.yaml
2) Environment variables:
       CVRESUME_ORCH_*

This allows:
- Safe local defaults via YAML
- Secure overrides in deployment environments
- No hard-coded secrets in source code

WHAT THIS FILE IS NOT FOR
-------------------------
This module is NOT responsible for:
- Business logic
- HTTP calls
- Service orchestration
- Request handling
- Feature implementation

It should only define *configuration structure and loading rules*.

DESIGN INTENT
-------------
- All runtime-configurable behavior MUST be declared here
- Adding a new config option requires:
    1) Adding a field to Settings
    2) Optionally documenting it in parameters/parameters.yaml
- Any missing required setting should fail fast at startup

This prevents silent misconfiguration and production surprises.

RECENT ADDITION
---------------
- preserve_container_keys:
    Controls response JSON key normalization behavior.
    These keys represent "free-form dict containers" where *inner keys*
    must be preserved exactly (not camelCased) during response conversion.
    Example: {"scores"} (default).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Set

import structlog
import yaml
from pydantic import AnyHttpUrl, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = structlog.get_logger(__name__)

PARAMETERS_PATH = Path(__file__).resolve().parents[2] / "parameters" / "parameters.yaml"


class Settings(BaseSettings):
    """
    Runtime settings for the CV Resume Evaluation Orchestrator API.

    Load order / precedence:
        1) YAML defaults (parameters/parameters.yaml)
        2) Environment variables (CVRESUME_ORCH_*), overriding YAML
    """

    model_config = SettingsConfigDict(
        env_prefix="CVRESUME_ORCH_",
        extra="ignore",
    )

    # Service metadata
    service_name: str = "cvresume_evaluation_orchestrator"
    environment: str = "local"
    log_level: str = "INFO"

    # Sister service URLs
    # Optional at the model level to allow partial env loading;
    # enforced explicitly in get_settings().
    data_api_base_url: Optional[AnyHttpUrl] = None
    evaluation_api_base_url: Optional[AnyHttpUrl] = None

    # Internal networking timeouts
    # - http_timeout_seconds: general HTTP calls (e.g. Data API)
    # - evaluation_timeout_seconds: long-running evaluator / LLM calls
    http_timeout_seconds: float = 60.0
    evaluation_timeout_seconds: float = 180.0
    max_retries: int = 2

    # Request tracing
    request_id_header: str = "X-Request-ID"

    # Response JSON normalization
    preserve_container_keys: Set[str] = Field(
        default_factory=lambda: {"scores"},
        description=(
            "Container keys whose *inner dict keys* must be preserved (not camelCased) "
            "during response normalization. Use for free-form dict containers."
        ),
    )

    # Feature flags
    enable_debug_metadata: bool = Field(
        default=False,
        description="If true, orchestrator may include evaluator metadata fields in responses/logs.",
    )

    enable_role_with_skills_and_responsibilities_str: bool = Field(
        default=False,
        description=(
            "If true, DataFetcher will enrich role_core response with a prompt-ready "
            "role_context string (skills + responsibilities)."
        ),
    )


@lru_cache(maxsize=1)
def _load_yaml_parameters() -> Dict[str, Any]:
    """
    Load base configuration from parameters/parameters.yaml.

    Cached to:
    - Avoid repeated disk I/O
    - Guarantee consistent config during process lifetime
    """
    if not PARAMETERS_PATH.exists():
        logger.warning("parameters_yaml_missing", expected=str(PARAMETERS_PATH))
        return {}

    try:
        with PARAMETERS_PATH.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            logger.warning(
                "parameters_yaml_not_dict",
                path=str(PARAMETERS_PATH),
                type=type(data).__name__,
            )
            return {}
        logger.info("parameters_yaml_loaded", path=str(PARAMETERS_PATH))
        return data
    except Exception as exc:  # noqa: BLE001
        logger.error("parameters_yaml_load_error", path=str(PARAMETERS_PATH), error=str(exc))
        return {}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Construct and return the final validated Settings object.

    This function is:
    - Cached (singleton per process)
    - The ONLY supported way to access runtime settings

    Any code needing configuration should call this function,
    not instantiate Settings() directly.
    """
    # 1) YAML defaults
    yaml_data = _load_yaml_parameters()

    # 2) env overrides (partial)
    try:
        env_settings = Settings()
        env_data = env_settings.model_dump(exclude_unset=True)
        logger.info("settings_loaded_env_only_partial", fields=list(env_data.keys()))
    except ValidationError as exc:
        logger.warning("settings_env_validation_error", errors=exc.errors())
        env_data = {}

    # 3) merge
    merged: Dict[str, Any] = {**yaml_data, **env_data}

    # 4) enforce required URLs
    missing: list[str] = []
    if not merged.get("data_api_base_url"):
        missing.append("data_api_base_url")
    if not merged.get("evaluation_api_base_url"):
        missing.append("evaluation_api_base_url")

    if missing:
        logger.error("settings_missing_required_urls", missing=missing, yaml_path=str(PARAMETERS_PATH))
        raise RuntimeError(
            f"Missing required settings: {', '.join(missing)}. "
            "Set them either in environment variables (CVRESUME_ORCH_*) "
            f"or in {PARAMETERS_PATH}."
        )

    # 5) final validation
    settings = Settings.model_validate(merged)

    logger.info(
        "settings_loaded",
        environment=settings.environment,
        service_name=settings.service_name,
        data_api_base_url=str(settings.data_api_base_url),
        evaluation_api_base_url=str(settings.evaluation_api_base_url),
        http_timeout_seconds=settings.http_timeout_seconds,
        evaluation_timeout_seconds=settings.evaluation_timeout_seconds,
        max_retries=settings.max_retries,
        preserve_container_keys=sorted(settings.preserve_container_keys),
        enable_debug_metadata=settings.enable_debug_metadata,
        enable_role_with_skills_and_responsibilities_str=settings.enable_role_with_skills_and_responsibilities_str,
    )

    return settings
