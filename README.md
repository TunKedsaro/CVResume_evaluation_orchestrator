# CV Resume evaluator API

The **Resume Evaluation Orchestrator API** is a **Backend-for-Frontend (BFF)** service responsible for orchestrating **end-to-end resume evaluation** across internal services and LLM pipelines.

It provides a **single, stable, frontend-facing API** while encapsulating orchestration logic such as request validation, data normalization, logging and controlled invocation of the resume evaluation pipeline.

---

## High-Level Purpose
- Shield frontend clients from:
    - Multiple backend services
    - Internal evaluation mechanics
    - LLM prompt and scoring complexit
- Enforce **strict input validation and safety guarantees**
- Orchestrate resume evaluation in a **deterministic, auditable, schema-driven manner**
- Enable future evolution of data sources (e.g. BigQuery, Data APIs) **without breaking clients**

--- 

## Architecture Overview
The Orchestrator coordinates the following components:
### 1. External Clients
- Frontend applications
- CV Generator service
- Other internal services
All exteranl consumers interact **only** with this Orchestrator API

### 2. Internal Orchestrator API (This Service)
Runs on **Cloud Run** and is responsible for:
- Validating incoming API requests
- Normalizing inputs into interal schemas
- Orchestrating the resume evaluation pipeline
- Logging request, latency, and cost metadata
- Returning a stable response envelope

### 3. Resume Evaluation Pipeline (Cloud Run)
1. **PromptBuilder**
    - YAML-driven prompt construction
    - Section + Criteria-aware prompts
2. **LLMCaller**
    - Calls Gemini models
    - Handles retries, latency measurement, token accounting
3. **Section Score aggregator**
    - Aggregates criterion-level scores per section
4. **Global Aggregator**
    - Computes final resume score and section contributions
5. **Output Service**
    - Normalizes evaluation output for API response

### 4. Logging & Observability
- Centralized logging via **Google Cloud Logging**
- Structured logs for:
  - Request lifecycle
  - LLM usage
  - Latency
  - Errors

---

## End-to-End Flow
```text
Client
|
| POST /api/v1/resume-evaluations
v
Resume Evaluation Orchestrator API
    ├─ Validate request & enums
    ├─ Normalize input payload
    ├─ (Optional) Mock data gathering
    ├─ Invoke PromptBuilder
    ├─ Call LLM (Gemini)
    ├─ Aggregate section & global scores
    ├─ Log metadata (latency, cost, status)
    └─ Return stable response envelope
```

---

## Responsibilities (Detailed)
### 1. External Request Validation
- Accepts **structured resume input and evaluation options**
- Rejects:
  - Invalid schema
  - Unsupported enums
  - Malformed section payloads
- Ensures predictable and injection-safe behavior

**Request naming policy**

- ✅ Preferred: **camelCase** at API boundary
- ✅ Backward compatible: **snake_case** accepted
- ✅ Internally normalized via typed models

---

### 2. Input Normalization

The orchestrator normalizes incoming data into an internal evaluation payload that:

- Is compatible with the PromptBuilder
- Enforces section-level constraints
- Prevents user-injected instructions from leaking into prompts

---

### 3. Evaluation Pipeline Orchestration

- Executes the evaluation pipeline sequentially:
  - Prompt building
  - LLM invocation
  - Section scoring
  - Global aggregation
- Applies:
  - Timeout control
  - Structured error handling
- Does **not** expose internal pipeline stages to clients

---

### 4. Response Normalization

Returns a **stable response envelope** that includes:

- Final resume score
- Section-level scores and feedback
- Contribution breakdown
- Structured metadata (latency, model, cost)
- Optional raw evaluation output (for audit/debug)

**Response naming policy**

- ✅ **camelCase enforced** at API boundary (success + error)

---

## API Specification

📄 **Authoritative API contract** is documented in:
```

api_spec/API_spec.md

```

The API spec includes:

- Full request & response schemas
- Optional vs required fields
- Supported enum values
- Validation rules
- Error formats
- Example requests and responses

> **README = conceptual & operational overview**  
> **API_spec.md = contract you code against**

---

## Supported Evaluation Modes
The same endpoint supports multiple evaluation modes:
1. **Basic Resume Evaluation**
    - No role or JD provided
    - General quality assessment
2. **Role-Aware Evaluation**
    - Role taxonomy provided
    - Role relevance scoring enabled
3. **JD-Aware Evaluation**
    - Job description taxonomy provided
    - Skill and experience alignment evaluated

Role and JD are **optional**, but **strictly validated if present**.

---

## Current Supported Enums
### Language
- `en`
- `th`

---

## Project Structure
```text
.
├── Dockerfile.dev
├── Dockerfile.prod
├── README.md
├── cloudbuild.yaml
├── docs
│   └── API_spec.md        # Formal API contract
├── requirements.txt
└── src
    └── main.py            # FastAPI app + public endpoints
```

## Configuration

---

## API Endpoints (Summary)
### Health Check

**GET `/health`

Used for Cloud Run liveness and monitoring.
```json
{
  "status": "ok",
  "service": "resume_evaluation_orchestrator",
  "environment": "prod"
}
```

### Create Resume Evaluation
**POST `/api/v1/resume-evaluations**
Primary endpoint for all cvresume evaluation modes.

➡️ See **`docs/API_spec.md`** for full contract details.

--- 

## Deployment (Cloud Run)
```text
gcloud builds submit \
  --config=cloudbuild.yaml \
  --project=poc-piloturl-nonprod

gcloud run deploy cv-orchestrator-service \   
  --image="asia-southeast1-docker.pkg.dev/poc-piloturl-nonprod/cv-orchestrator/cv-orchestrator:latest" \   
  --region="asia-southeast1" \   
  --port=4000 \   
  --memory=2Gi \   
  --cpu=2 \   
  --max-instances=5 \   
  --set-env-vars="APP_ENV=prod,GOOGLE_API_KEY=AIza...Rk" \   
  --allow-unauthenticated
```

---

## Current Status
* ✅ API structure finalized
* ✅ Evaluation orchestration flow defined
* ✅ Logging integration in place
* ✅ Cloud Run compatible
* ⚠️ BigQuery & Data Gathering integration not yet implemented

