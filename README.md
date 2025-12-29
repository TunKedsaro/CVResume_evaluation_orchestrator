# CV Resume Evaluation Orchestrator API (BFF)

The **CV Resume Evaluation Orchestrator API** is a **Backend-for-Frontend (BFF)** service that orchestrates **end-to-end resume evaluation** by validating requests, normalizing payloads, optionally enriching with role metadata, and invoking a downstream **LLM-based evaluator**.

It provides a **single, stable, frontend-facing API** while encapsulating orchestration logic such as schema validation, naming normalization (camelCase/snake_case), correlation IDs, dependency handling, and consistent response envelopes.

---

## High-Level Goals

This service exists to:

- **Shield frontend clients** from:
  - multiple backend services and evolving internal endpoints
  - LLM prompt/scoring mechanics and evaluator contract changes
  - role lookup and enrichment logic
- Enforce **strict input validation** and predictable behavior
- Provide an **auditable, traceable execution path** (correlation IDs + structured logs)
- Enable future evolution of internal components (Data APIs, different evaluators, new modes)
  **without breaking clients**

---

## Runtime & Hosting

- Runs on **Google Cloud Run**
- Exposes:
  - health endpoints: `/health` and `/healthz`
  - versioned REST evaluation endpoint: `/api/v1/resume-evaluations`
  - OpenAPI:
    - Swagger UI: `/docs`
    - OpenAPI JSON: `/openapi.json`

**Production URL**
- https://cvresume-eval-orchestrator-810737581373.asia-southeast1.run.app

---

## Architecture Overview

### Components

1) **External Clients**
- Frontend applications
- Internal services (e.g., CV generator, workflow tools)
- Test harnesses / QA automation

All external consumers interact **only** with this Orchestrator API.

2) **Orchestrator API (This Service)**
Responsibilities:
- Validate request payload and enums (and API version header)
- Accept **camelCase and snake_case** request fields at top-level
- Normalize request into internal schema (snake_case internal canonical)
- (Optional) fetch role metadata and build role context
- Call downstream evaluator with correlation ID passthrough
- Normalize evaluator output into a stable response schema
- Return frontend-safe envelope + consistent error format

3) **Downstream Resume Evaluation Service (Evaluator)**
A separate Cloud Run service that performs the LLM-based evaluation:
- prompt construction (YAML-driven)
- LLM invocation (Gemini)
- criterion-level scoring per section
- aggregation into overall score and per-section contribution
- response formatting (which may evolve over time)

4) **Logging & Observability**
- Structured logs in **Google Cloud Logging**
- Correlation ID propagation:
  - incoming `X-Correlation-Id` is echoed back
  - if absent, server generates a `corr_<uuid>` and forwards downstream
- Logs include:
  - request lifecycle events
  - dependency calls and outcomes
  - latency measurements
  - errors (with normalized error envelopes)

---

## End-to-End Flow

```text
Client
|
| POST /api/v1/resume-evaluations
|   (optional: X-Correlation-Id)
v
Resume Evaluation Orchestrator API
    ├─ Validate request payload + enums
    ├─ Validate X-API-Version header (must be "1")
    ├─ Normalize top-level naming (camelCase/snake_case)
    ├─ If targetRole provided:
    │     ├─ Fetch role core metadata from Data API
    │     └─ (feature-flagged) build role_context string
    ├─ Call downstream evaluator service
    ├─ Normalize evaluator response into stable schema
    ├─ Emit structured logs (latency, dependency outcomes)
    └─ Return stable response envelope (camelCase)
````

---

## What the Orchestrator Does (Detailed)

### 1) Request Validation

* Accepts **structured resume JSON** via:

  * `resumeJson` (preferred)
  * `resume_json` (backward compatible)
* Accepts an **optional role**:

  * `targetRole` / `target_role` (optional)
* Accepts an optional output language:

  * `outputLang` / `output_lang` (default: `en`)

Rejects:

* invalid JSON body / schema mismatch (`400`)
* unsupported API version (`400`)
* invalid enum values (`400`)

**Request naming policy**

* ✅ Preferred: **camelCase** at the API boundary
* ✅ Backward compatible: **snake_case** accepted for the same top-level fields
* ✅ Internally normalized into typed Python models

> Note: only the top-level request fields are normalized/aliased.
> The nested content under `resumeJson` is treated as **free-form structured data**.

---

### 2) Optional Role Enrichment (Role-Aware Mode)

If `targetRole` is provided:

* Orchestrator calls `eport_data_api` to resolve role metadata
* Role metadata may be used to:

  * resolve a human-readable role name (for evaluator prompts)
  * build a `role_context` string (feature-flagged)

If `targetRole` is omitted:

* Orchestrator performs a **role-agnostic evaluation**
* No role lookup is executed

---

### 3) Downstream Evaluator Invocation

* Calls evaluator endpoint:

  * `POST /evaluation/final-resume-score-async` (downstream; internal)
* Forwards:

  * normalized payload
  * `X-Correlation-Id`
* Applies evaluator-specific timeout settings
* Treats evaluator failures as dependency failures (surfaced as `502`)

---

### 4) Response Normalization (Stable Contract)

Downstream evaluator responses are normalized into a stable internal structure:

* Handles legacy quirks (e.g., `conclution` → `conclusion`)
* Extracts and returns:

  * `conclusion.finalResumeScore`
  * `conclusion.sectionContribution`
  * `sectionDetail` per resume section (scores + feedback)

**Response naming policy**

* ✅ **camelCase enforced** at API boundary (success + error)
* ✅ Some nested dict containers may preserve keys (e.g. `scores`) to avoid rewriting free-form dictionaries

---

## Supported Evaluation Modes

The same endpoint supports multiple modes:

1. **Basic / Role-Agnostic Evaluation**

* `targetRole` omitted
* evaluates general resume quality and completeness

2. **Role-Aware Evaluation**

* `targetRole` provided
* enables role relevance scoring and optional role context enrichment

> JD-aware evaluation is not exposed in the current public contract (yet).
> Keep it in “planned” until an actual request field + implementation exists.

---

## API Specification (Authoritative)

📄 The authoritative API contract lives here:

```text
api_spec/API_spec.md
```

Includes:

* request/response schemas
* optional vs required fields
* enum values
* status codes
* standard error format
* example requests and responses

> README = conceptual + operational overview
> API_spec.md = contract you code against

---

## API Endpoints (Summary)

### Health Check

**GET `/health`** (canonical)
**GET `/healthz`** (convenience)

Example response:

```json
{
  "status": "ok",
  "service": "cvresume_evaluation_orchestrator",
  "environment": "prod"
}
```

Headers (example):

```http
X-Correlation-Id: corr_...
X-API-Version: 1
```

---

### Create Resume Evaluation

**POST `/api/v1/resume-evaluations`**
Primary endpoint for all supported evaluation modes.

➡️ See `api_spec/API_spec.md` for the full contract.

---

## Request Examples

### 1) Role-Agnostic (recommended for generic scoring)

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

### 2) Role-Aware (role taxonomy ID provided)

```json
{
  "resumeJson": {
    "profile": {
      "title": "AI Engineer / ML Engineer",
      "yearsExperience": 6
    }
  },
  "targetRole": "role#ai_engineer",
  "outputLang": "en"
}
```

### 3) Snake_case compatibility

```json
{
  "resume_json": {
    "profile": {
      "title": "AI Engineer",
      "years_experience": 6
    }
  },
  "target_role": "role#ai_engineer",
  "output_lang": "en"
}
```

---

## Response Example (Success)

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

---

## Error Handling

### Status Codes

| Code | Meaning                                   |
| ---: | ----------------------------------------- |
|  200 | Evaluation successful                     |
|  400 | Validation failed / invalid API version   |
|  404 | Referenced role not found (if applicable) |
|  502 | Downstream / dependency failure           |
|  500 | Unexpected internal error                 |

### Standard Error Envelope

All errors follow a consistent schema:

```json
{
  "code": "VALIDATION_FAILED",
  "message": "Validation failed",
  "subErrors": [
    {
      "field": "target_role",
      "errors": [
        { "code": "missing", "message": "Field required" }
      ]
    }
  ],
  "timestamp": 1750672014,
  "correlationId": "corr_abc123"
}
```

---

## Headers

### Correlation ID

* Clients **may** set: `X-Correlation-Id`
* Server echoes it back in response headers
* If not provided, server generates one

```http
X-Correlation-Id: corr_local_123
```

### API Version

```http
X-API-Version: 1
```

Unsupported versions return `400 INVALID_FIELD_VALUE`.

---

## Configuration

This repo uses:

* YAML defaults under `parameters/parameters.yaml`
* Environment variables in Cloud Run deployment to override runtime config

Common runtime variables (names as used in your deploy command):

* `CVRESUME_ORCH_DATA_API_BASE_URL`
* `CVRESUME_ORCH_EVALUATION_API_BASE_URL`
* `LOG_LEVEL`
* `HTTP_TIMEOUT_SECONDS`
* `MAX_RETRIES`
* `ENABLE_DEBUG_METADATA`

(See also: `functions/utils/settings.py` and `parameters/parameters.yaml`.)

---

## Local Development

### 1) Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Run locally

Run the FastAPI app (example):

```bash
uvicorn api:app --host 0.0.0.0 --port 8091 --reload
```

Health check:

```bash
curl -sS http://127.0.0.1:8091/health | jq .
```

### 3) Run tests

Unit tests:

```bash
pytest -q
```

Local integration tests (hits your local server):

```bash
pytest -q tests/local_api_actual_tests.py
```

GCP integration tests (hits Cloud Run URL):

```bash
pytest -q tests/gcp_api_actual_tests.py
```

---

## Deployment (Cloud Run)

### Build (Cloud Build)

```bash
gcloud builds submit \
  --config=cloudbuild.yaml \
  --project=poc-piloturl-nonprod
```

### Deploy (example used in latest verification)

```bash
gcloud run deploy "$SERVICE_NAME" \
  --image "$IMAGE" \
  --region "$REGION" \
  --service-account "cv-eval-orchestrator-sa@$PROJECT_ID.iam.gserviceaccount.com" \
  --allow-unauthenticated \
  --port 8080 \
  --timeout 300 \
  --set-env-vars \
CVRESUME_ORCH_DATA_API_BASE_URL="https://eport-data-api-810737581373.asia-southeast1.run.app",\
CVRESUME_ORCH_EVALUATION_API_BASE_URL="https://cvresume-service-810737581373.asia-southeast1.run.app",\
LOG_LEVEL="INFO",\
HTTP_TIMEOUT_SECONDS="30",\
MAX_RETRIES="2",\
ENABLE_DEBUG_METADATA="true"
```

After deploy, verify:

```bash
pytest -q tests/gcp_api_actual_tests.py
```

---

## Repository Structure (Actual)

```text
.
├── Dockerfile
├── README.md
├── api.py
├── api_spec
│   └── API_spec.md
├── cloudbuild.yaml
├── functions
│   ├── orchestrator
│   │   ├── data_fetcher.py
│   │   ├── resume_evaluation_service.py
│   │   ├── role_context_assembler.py
│   │   └── status_normalizer.py
│   └── utils
│       ├── http_client.py
│       ├── json_naming_converter.py
│       └── settings.py
├── parameters
│   ├── config.yaml
│   └── parameters.yaml
├── schemas
│   ├── input_schema.py
│   └── output_schema.py
└── tests
    ├── gcp_api_actual_tests.py
    ├── local_api_actual_tests.py
    ├── test_payloads
    │   ├── test1.json
    │   ├── test2.json
    │   ├── test3.json
    │   ├── test4.json
    │   └── test5.json
    └── ...
```

---

## Current Status

* ✅ REST endpoint `/api/v1/resume-evaluations` live on Cloud Run
* ✅ camelCase + snake_case top-level request fields supported and tested
* ✅ `targetRole` optional (role-agnostic supported) and tested end-to-end
* ✅ local + GCP integration test suites passing (including test5 without role)
* ✅ standardized error envelope and correlation headers

---

## Roadmap (Near-Term)

* Authentication enforcement (gateway JWT / internal API key)
* Confirm legacy endpoint status (`/v1/orchestrator/evaluate-cvresume`) and deprecate if safe
