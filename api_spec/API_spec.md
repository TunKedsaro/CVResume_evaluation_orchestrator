# CV Resume Evaluation Orchestrator API — REST API Specification

Service: **resume-evaluations**  
Repository: https://github.com/nachai-l/CVResume_evaluation_orchestrator/

Purpose:  
Evaluate structured CV / resume content by orchestrating **request validation**, **optional role metadata lookup**, and the **LLM-based resume evaluation pipeline**, returning section-level and overall scores in a stable contract.

---

## Base URLs

**Production (Cloud Run):**  
https://cvresume-eval-orchestrator-810737581373.asia-southeast1.run.app

**Local:**  
http://127.0.0.1:8091

**Swagger / OpenAPI (prod):**
- Swagger UI: https://cvresume-eval-orchestrator-810737581373.asia-southeast1.run.app/docs
- OpenAPI JSON: https://cvresume-eval-orchestrator-810737581373.asia-southeast1.run.app/openapi.json

---

## Guideline Alignment Notes

- ✅ **Resource-based REST endpoint**
- ✅ **HTTP method:** `POST` used for execution-style evaluation
- ✅ **HTTP status codes:** `200 OK` for successful evaluation
- ✅ **Error format:** standard schema `{code, message, subErrors, timestamp, correlationId}`
- ✅ **Correlation ID:** `X-Correlation-Id` supported (passthrough + server-generated)
- ✅ **API Version header:** `X-API-Version` supported (currently `1`)
- ✅ **Naming convention:** lowercase, kebab-case URLs
- ✅ **JSON naming (request):** camelCase **and** snake_case accepted (**verified local + Cloud Run tests**)
- ✅ **JSON naming (response):** camelCase enforced for envelope and nested fields, with support for preserving inner keys for free-form containers (e.g. `scores`) via `preserve_container_keys`

> Note on response naming: response keys are camelCased at the API boundary by `convert_keys_snake_to_camel()`.  
> Some container objects may preserve their inner keys (e.g., `scores`) to avoid altering free-form dictionaries.

---

## Authentication & Authorization

**Not enforced yet — future-ready**

Designed to support:

### External Gateway (Bearer JWT)

```http
Authorization: Bearer <token>
````

### Internal Network (X-API-Key)

```http
X-API-Key: <key>
```

### Gateway → Internal Header Mapping (planned)

```http
X-User-Id
X-User-Name
X-User-Email
X-User-Roles
```

---

## Required Headers

### Content-Type

```http
Content-Type: application/json
```

### Correlation ID

* Client **may provide** `X-Correlation-Id`
* If missing, server generates: `corr_<uuid>`
* Always echoed in response headers

Example:

```http
X-Correlation-Id: corr_abc123
```

### API Version

```http
X-API-Version: 1
```

If unsupported → `400 INVALID_FIELD_VALUE`

---

## Endpoints Summary

### Health

* `GET /health` ✅ canonical
* `GET /healthz` ✅ supported (non-canonical / convenience)

### Resume Evaluation (REST)

* `POST /api/v1/resume-evaluations` ✅ primary

### Legacy / Deprecated

* `POST /v1/orchestrator/evaluate-cvresume` ⚠️ legacy alias (if still enabled; not required for GCP usage)
* `POST /evaluation/final-resume-score-async` ⚠️ internal downstream service (not part of this orchestrator public contract)

---

## 1) Health Endpoint

### GET /health

**200 OK**

```json
{
  "status": "ok",
  "service": "cvresume_evaluation_orchestrator",
  "environment": "prod"
}
```

Response headers include:

```http
X-Correlation-Id: corr_...
X-API-Version: 1
```

---

## 2) Resume Evaluation

### POST /api/v1/resume-evaluations

Executes a full resume evaluation by:

* validating request payload
* optionally looking up role core metadata from Data API (if `target_role` is provided)
* generating role context string (feature-flagged; only if role is provided)
* invoking LLM-based evaluation (downstream)
* aggregating section-level and overall scores
* returning a stable evaluation response

---

### Status Codes

| Code | Meaning                                   |
| ---: | ----------------------------------------- |
|  200 | Evaluation successful                     |
|  400 | Validation failed / invalid API version   |
|  404 | Referenced role not found (if applicable) |
|  502 | Downstream / dependency failure           |
|  500 | Unexpected internal error                 |

> Note: Current implementation surfaces most dependency failures as `502` (e.g., role lookup failures, evaluator failures).

---

## Request Schema

Design note:
The orchestrator accepts **structured resume JSON** directly.

* If `target_role` / `targetRole` is provided, the orchestrator will fetch role metadata to resolve a `target_role_name` and may enrich the evaluator input with `role_context`.
* If `target_role` is omitted, the orchestrator performs a **role-agnostic** evaluation (generic resume quality scoring).

### Request JSON naming

This endpoint accepts **both**:

* `snake_case` field names (e.g., `resume_json`)
* `camelCase` field names (e.g., `resumeJson`)

Implemented via Pydantic field aliases + `populate_by_name=True`, and **verified** by local + Cloud Run integration tests.

---

### Example (snake_case) — role provided

```json
{
  "resume_json": {
    "profile": {
      "title": "Senior AI Engineer",
      "years_experience": 6
    },
    "summary": [
      "AI/ML Engineer with 6+ years of experience in production systems."
    ],
    "education": [
      {
        "institution": "University of Tokyo",
        "degree": "M.Sc. Computer Science"
      }
    ],
    "experience": [
      {
        "title": "AI Engineer",
        "company": "Tech Corp",
        "description": [
          "Built production RAG pipelines"
        ]
      }
    ],
    "skills": {
      "skills": ["Python", "LLMs", "GCP"]
    }
  },
  "target_role": "role#ai_engineer",
  "output_lang": "en"
}
```

### Example (camelCase) — role provided

```json
{
  "resumeJson": {
    "profile": {
      "title": "Senior AI Engineer",
      "yearsExperience": 6
    }
  },
  "targetRole": "role#ai_engineer",
  "outputLang": "en"
}
```

### Example — role omitted (role-agnostic)

```json
{
  "resumeJson": {
    "profile": {
      "title": "Software Engineer",
      "yearsExperience": 4
    },
    "summary": [
      "Backend engineer with experience in APIs and cloud deployments."
    ]
  },
  "outputLang": "en"
}
```

> Important:
>
> * Only the **top-level request fields** support snake/camel dual naming.
> * The inner structure of `resume_json` / `resumeJson` is treated as free-form structured data and is not normalized by the orchestrator.

---

### Field Definitions

| Field                    | Type   | Required | Notes                                                               |
| ------------------------ | ------ | -------: | ------------------------------------------------------------------- |
| resume_json / resumeJson | object |        ✅ | Structured resume content                                           |
| target_role / targetRole | string |        ❌ | Role taxonomy ID (if provided: fetch role core, resolve role title) |
| output_lang / outputLang | enum   |        ❌ | `en`, `th` (default: `en`)                                          |

---

## Successful Response

**200 OK**

Headers:

```http
X-Correlation-Id: corr_...
X-API-Version: 1
```

Body (example):

```json
{
  "status": "success",
  "data": {
    "conclusion": {
      "finalResumeScore": 27.6,
      "sectionContribution": {
        "Profile": {
          "sectionTotal": 20.0,
          "sectionWeight": 0.1,
          "contribution": 2.0
        }
      }
    },
    "sectionDetail": {
      "Profile": {
        "totalScore": 20.0,
        "scores": {
          "ContentQuality": {
            "score": 10.0,
            "feedback": "..."
          }
        }
      }
    }
  },
  "correlationId": "corr_abc123",
  "metadata": null
}
```

Notes:

* `status` is always `"success"` for HTTP `200`.
* `metadata` is typically `null` in successful responses.
* Response keys are camelCased at the API boundary via `convert_keys_snake_to_camel()`.
* Some container objects may preserve their inner keys (e.g., `scores`) based on `preserve_container_keys`.

---

## Standard Error Format

All errors follow this schema:

```json
{
  "code": "VALIDATION_FAILED",
  "message": "Validation failed",
  "subErrors": [
    {
      "field": "target_role",
      "errors": [
        {
          "code": "missing",
          "message": "Field required"
        }
      ]
    }
  ],
  "timestamp": 1750672014,
  "correlationId": "corr_abc123"
}
```

---

## Enumerations

### output_lang / outputLang

* `en`
* `th`

---

## Internal Dependencies

### eport_data_api (optional)

* Role core lookup (only if role_id is provided)
* Optional role context enrichment (feature-flagged)
* Retry + timeout handling

### Resume Evaluation Service (downstream evaluator)

* PromptBuilder (YAML-driven)
* LLM execution (Gemini)
* Section scoring
* Global aggregation

---

## Configuration Notes (parameters.yaml)

Key runtime fields:

* `data_api_base_url`
* `evaluation_api_base_url`
* `http_timeout_seconds`
* `evaluation_timeout_seconds`
* `max_retries`
* `enable_debug_metadata`
* `enable_role_with_skills_and_responsibilities_str`
* `preserve_container_keys` (e.g., `scores`)

> Deployment note (Cloud Run env vars):
>
> * Prefer `EVALUATION_TIMEOUT_SECONDS` (not `GENERATION_TIMEOUT_SECONDS`) to control the evaluator call timeout.
> * Ensure your `functions/utils/settings.py` maps env vars → settings keys consistently.

---

## Change Log (Consolidated)

### 2025-12-19 — Initial Core Evaluation API

* Defined structured resume input contract
* Standardized evaluation response schema
* Introduced section-level scoring
* Introduced `/v1/orchestrator/evaluate-cvresume`

---

### 2025-12-29 — Orchestrator Refactor, Deploy & Hardening

* Published Production Cloud Run URL:

  * `https://cvresume-eval-orchestrator-810737581373.asia-southeast1.run.app`
* Exposed Swagger / OpenAPI in prod:

  * `/docs`, `/openapi.json`
* Added REST endpoint `/api/v1/resume-evaluations`
* Added `X-Correlation-Id` passthrough + generation
* Added `X-API-Version` header validation (v=1)
* Introduced standardized error schema
* Added dependency failure surfacing as `502`
* Added role context enrichment from Data API (feature-flagged)
* Normalized legacy evaluator responses into stable contract
* Added Settings system (YAML + env merge)
* Added local + GCP actual integration test suites
* Improved observability (timing, correlation headers)
* Fixed missing runtime deps during deploy (e.g., `structlog`, `requests`)

---

### 2025-12-29 — Request Contract Completion (camelCase + snake_case)

* Implemented camelCase aliases in `ResumeEvaluationRequest`:

  * `resume_json` ↔ `resumeJson`
  * `target_role` ↔ `targetRole`
  * `output_lang` ↔ `outputLang`
* Enabled `populate_by_name=True` to accept snake_case and camelCase simultaneously
* Verified via:

  * `tests/local_api_actual_tests.py` (5/5 payloads pass, including role omitted)
  * `tests/gcp_api_actual_tests.py` (5/5 payloads pass, including role omitted)

---

### 2025-12-29 — Spec Update: Make `target_role` Optional

* Updated API contract so `target_role` / `targetRole` is optional:

  * If provided: role-aware evaluation (role lookup + role context enrichment may apply)
  * If omitted: role-agnostic evaluation (generic scoring)
* Verified end-to-end (local + Cloud Run) with payloads that omit `targetRole` (test5).

---

### 2025-12-29 — Deployment Verified on Cloud Run

* Deployed revision and verified live behavior using:

  * `gcloud run deploy ...`
  * `tests/gcp_api_actual_tests.py` (2 tests pass; evaluation payload suite 5/5)

---

### Planned / Pending

* Authentication enforcement
* Legacy endpoint deprecation confirmation / removal
* Optional debug metadata response (behind flag; ensure no sensitive leakage)

---
