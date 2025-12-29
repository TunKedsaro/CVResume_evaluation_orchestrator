"""
api.py

WHAT THIS FILE IS FOR
---------------------
This module defines the FastAPI application entrypoint for the
CV Resume Evaluation Orchestrator API.

It is responsible for:
- Creating the FastAPI app instance (title/version/description)
- Registering middleware for:
    - Correlation ID propagation (X-Correlation-Id)
    - API version validation (X-API-Version)
- Defining standard error responses using a consistent schema:
    {code, message, subErrors, timestamp, correlationId}
- Registering exception handlers for:
    - RequestValidationError (400 VALIDATION_FAILED)
    - HTTPException passthrough (with standardized envelope)
- Exposing HTTP endpoints:
    - GET /health and /healthz
    - POST /api/v1/resume-evaluations (primary public contract)

REQUEST/RESPONSE CONTRACT RULES
-------------------------------
- Request payload accepts both camelCase and snake_case field names
  (handled by the Pydantic input schema).
- Response payload is enforced to be camelCase across nested objects.
  One exception is allowed: keys inside specified "free-form containers"
  are preserved verbatim (e.g., rubric categories under `scores`).

Naming normalization behavior:
- All keys are converted snake_case -> camelCase recursively
- Keys under preserve_container_keys are not renamed (e.g. "scores")
- Top-level envelope keys remain stable: {status, data, correlationId, metadata}

DESIGN INTENT
-------------
This file contains ONLY the HTTP layer:
- routing
- middleware
- exception handling
- response formatting / normalization

It must NOT contain:
- business logic
- downstream API logic (Data API / Evaluator calls)
- prompt building or evaluation logic

Those responsibilities live in:
- functions/orchestrator/*
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Optional

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from functions.orchestrator.data_fetcher import DataFetcher
from functions.orchestrator.role_context_assembler import RoleContextAssembler
from functions.orchestrator.resume_evaluation_service import ResumeEvaluationService
from functions.orchestrator.status_normalizer import normalize_orchestrator_status
from functions.utils.json_naming_converter import convert_keys_snake_to_camel
from functions.utils.settings import get_settings
from schemas.input_schema import ResumeEvaluationRequest
from schemas.output_schema import EvaluationConclusion, OrchestratorEnvelope, ResumeEvaluationResponse

logger = structlog.get_logger(__name__)

settings = get_settings()
svc = ResumeEvaluationService(settings)
fetcher = DataFetcher(settings)

app = FastAPI(
    title="CV Resume Evaluation Orchestrator",
    version="1.0.0",
    description="Backend-for-Frontend orchestrator for resume evaluation.",
)

CORRELATION_HEADER = "X-Correlation-Id"
API_VERSION_HEADER = "X-API-Version"
SUPPORTED_API_VERSIONS = {"1"}


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def _get_or_create_correlation_id(request: Request) -> str:
    incoming = request.headers.get(CORRELATION_HEADER)
    return incoming.strip() if incoming else f"corr_{uuid.uuid4().hex}"


def _get_api_version(request: Request) -> str:
    v = getattr(request.state, "api_version", None)
    return str(v) if v else request.headers.get(API_VERSION_HEADER, "1").strip() or "1"


def _std_error(
    *,
    code: str,
    message: str,
    correlation_id: str,
    http_status: int,
    api_version: str = "1",
    sub_errors: Optional[list[dict[str, Any]]] = None,
) -> JSONResponse:
    payload = {
        "code": code,
        "message": message,
        "subErrors": sub_errors or [],
        "timestamp": int(time.time()),
        "correlationId": correlation_id,
    }
    headers = {
        CORRELATION_HEADER: correlation_id,
        API_VERSION_HEADER: api_version,
    }
    return JSONResponse(status_code=http_status, content=payload, headers=headers)


# -------------------------------------------------------------------
# Middleware
# -------------------------------------------------------------------
@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    correlation_id = _get_or_create_correlation_id(request)
    request.state.correlation_id = correlation_id
    response = await call_next(request)
    response.headers[CORRELATION_HEADER] = correlation_id
    return response


@app.middleware("http")
async def api_version_middleware(request: Request, call_next):
    correlation_id = getattr(request.state, "correlation_id", f"corr_{uuid.uuid4().hex}")
    version = request.headers.get(API_VERSION_HEADER, "1").strip() or "1"

    if version not in SUPPORTED_API_VERSIONS:
        return _std_error(
            code="INVALID_FIELD_VALUE",
            message="Invalid API version",
            correlation_id=correlation_id,
            http_status=400,
            sub_errors=[
                {
                    "field": API_VERSION_HEADER,
                    "errors": [{"code": "isIn", "message": "Supported versions: 1"}],
                }
            ],
        )

    request.state.api_version = version
    response = await call_next(request)
    response.headers[API_VERSION_HEADER] = version
    return response


# -------------------------------------------------------------------
# Exception handlers
# -------------------------------------------------------------------
@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError):
    correlation_id = getattr(request.state, "correlation_id", f"corr_{uuid.uuid4().hex}")
    api_version = _get_api_version(request)

    sub_errors: list[dict[str, Any]] = []
    for err in exc.errors():
        field = ".".join(str(x) for x in err.get("loc", []) if x != "body") or "body"
        sub_errors.append(
            {
                "field": field,
                "errors": [{"code": err.get("type"), "message": err.get("msg")}],
            }
        )

    logger.info(
        "request_validation_failed",
        correlation_id=correlation_id,
        error_count=len(sub_errors),
    )

    return _std_error(
        code="VALIDATION_FAILED",
        message="Validation failed",
        correlation_id=correlation_id,
        http_status=400,
        api_version=api_version,
        sub_errors=sub_errors,
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    correlation_id = getattr(request.state, "correlation_id", f"corr_{uuid.uuid4().hex}")
    api_version = _get_api_version(request)

    logger.warning(
        "http_exception",
        correlation_id=correlation_id,
        status_code=exc.status_code,
        detail=str(exc.detail),
    )

    message = str(exc.detail.get("message")) if isinstance(exc.detail, dict) else str(exc.detail)
    sub_errors: list[dict[str, Any]] = []

    if isinstance(exc.detail, dict) and exc.detail.get("code"):
        sub_errors.append(
            {
                "field": "downstream",
                "errors": [{"code": exc.detail["code"], "message": message}],
            }
        )

    return _std_error(
        code="BAD_GATEWAY" if exc.status_code >= 500 else "HTTP_ERROR",
        message=message,
        correlation_id=correlation_id,
        http_status=exc.status_code,
        api_version=api_version,
        sub_errors=sub_errors,
    )


# -------------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------------
@app.get("/healthz")
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": settings.service_name,
        "environment": settings.environment,
    }


@app.post("/api/v1/resume-evaluations", response_model=OrchestratorEnvelope)
async def evaluate_resume(payload: ResumeEvaluationRequest, request: Request) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", f"corr_{uuid.uuid4().hex}")

    # output_lang default (defensive)
    output_lang = "en" if payload.output_lang is None else payload.output_lang

    # ---------------------------------------------------------------
    # 1) Resolve role (optional)
    # ---------------------------------------------------------------
    role_id: Optional[str] = payload.target_role.strip() if payload.target_role else None
    target_role_name: Optional[str] = None
    role_context: Optional[str] = None
    role_core: Optional[dict[str, Any]] = None

    if role_id:
        # 1a) Fetch role core (only if role_id provided)
        try:
            role_core = await fetcher.fetch_role_core(role_id)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail={"code": "DATA_API_FAILED", "message": str(exc)},
            )

        role_obj = role_core.get("role") if isinstance(role_core.get("role"), dict) else {}

        target_role_name = (
            role_obj.get("role_title")
            or role_obj.get("roleTitle")
            or role_obj.get("title")
            or role_core.get("role_title")
            or role_core.get("roleTitle")
            or role_core.get("title")
            or role_core.get("role_name")
            or role_core.get("name")
        )

        if not isinstance(target_role_name, str) or not target_role_name.strip():
            raise HTTPException(
                status_code=502,
                detail={"code": "ROLE_RESOLUTION_FAILED", "message": "Could not resolve role name"},
            )

        # 1b) Role context (feature-flagged)
        if settings.enable_role_with_skills_and_responsibilities_str:
            role_context = RoleContextAssembler.build(role_core)

            if settings.enable_debug_metadata:
                logger.info(
                    "role_context_generated",
                    correlation_id=correlation_id,
                    role_id=role_id,
                    has_role_context=bool(role_context),
                    length=len(role_context) if role_context else 0,
                )

    # ---------------------------------------------------------------
    # 2) Call evaluator
    #
    # Role is OPTIONAL:
    # - If target_role is provided, we resolve role name via Data API
    #   and optionally build role_context.
    # - If target_role is omitted, we run a role-agnostic evaluation
    #   by passing target_role=None (and role_context=None).
    # ---------------------------------------------------------------
    try:
        result = svc.evaluate(
            resume_json=payload.resume_json,
            target_role=target_role_name,  # Optional[str]
            role_context=role_context,      # Optional[str]
            output_lang=output_lang,
            correlation_id=correlation_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "EVALUATOR_CALL_FAILED", "message": str(exc)},
        )

    # ---------------------------------------------------------------
    # 3) Build stable orchestrator response
    # ---------------------------------------------------------------
    concl = result.get("conclusion", {}) if isinstance(result.get("conclusion"), dict) else {}
    final_score = float(concl.get("final_resume_score", 0.0))

    if settings.enable_debug_metadata:
        logger.info(
            "resume_evaluation_response_debug",
            correlation_id=correlation_id,
            final_score=final_score,
            has_section_detail=bool(result.get("section_detail")),
            response_time=result.get("response_time"),
            estimated_cost_thd=result.get("estimated_cost_thd"),
        )

    upstream_status = result.get("status")  # may be None
    status, original_status = normalize_orchestrator_status(
        http_status=200,
        upstream_status=upstream_status,
    )

    envelope = OrchestratorEnvelope(
        status=status,  # ALWAYS "success" for 200
        correlation_id=result.get("correlation_id") or correlation_id,
        data=ResumeEvaluationResponse(
            conclusion=EvaluationConclusion(
                final_resume_score=final_score,
                section_contribution=concl.get("section_contribution", {}) or {},
            ),
            section_detail=result.get("section_detail", {}) or {},
        ),
        metadata={"originalStatus": original_status} if original_status else None,
    )

    payload_dict = convert_keys_snake_to_camel(
        envelope.model_dump(),
        preserve_container_keys=getattr(settings, "preserve_container_keys", None),
    )

    return JSONResponse(status_code=200, content=payload_dict)
