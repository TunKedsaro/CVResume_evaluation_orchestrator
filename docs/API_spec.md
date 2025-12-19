# CV Resume Evaluation Orchestrator API — REST API Specification

Service: **resume_evaluation_orchestrator (BFF)**  
Purpose: Evaluate structured CV / resume content by orchestrating **input normalization**, **role validation (optional)**, and the **LLM-based resume evaluation pipeline**.

---

## Base URLs
**Production (Cloud Run):** [https://cv-orchestrator-service-du7yhkyaqq-as.a.run.app](https://cv-orchestrator-service-du7yhkyaqq-as.a.run.app)

**Local :**[http://127.0.0.1:8000](http://127.0.0.1:8000)

**Swagger / OpenAPI (prod):** [https://cv-orchestrator-service-du7yhkyaqq-as.a.run.app/docs](https://cv-orchestrator-service-du7yhkyaqq-as.a.run.app/docs)

---

## Guideline Alignment Notes

* ✅ **Endpoint-based orchestration API**
* ✅ **HTTP method:** `POST` used for evaluation execution
* ✅ **HTTP status codes:** `200 OK` for successful evaluation
* ✅ **Error format:** standard error schema `{code,message,subErrors,timestamp,correlationId}`
* ✅ **Correlation ID:** `X-Correlation-Id` supported (passthrough + server-generated) ???
* ✅ **API Version header:** `X-API-Version` supported (currently `1`) ???
* ✅ **Naming convention:** URL lowercase + kebab-case
```json
/resume-evaluation
```
* ✅ **JSON naming (request):** **camelCase + snake_case accepted**
```json
client -> core
{
  "workExperience": [...]        //camelCase
}
or
{
  "work_experience": [...]       //snake_case
}
```
* ✅ **JSON naming (response):** **camelCase enforced**
```json
core -> response
{
  "overallScore": 85,            //camelCase
  "roleMatch": true              //camelCase
}
```
> Response camelCase is enforced at the API boundary.  
> Error responses also follow camelCase.

---


## Authentication & Authorization

**[Not enforced — future-ready]**

The API is designed to support:

### External Gateway (Bearer JWT)

Authorization: Bearer

### Internal Network (X-API-Key)

X-API-Key:

### Gateway → Internal Header Mapping (recommended)

**[In Progress — not implemented]**
X-User-Id: <jwt.sub>
X-User-Name: <jwt.name>
X-User-Email: <jwt.email>
X-User-Roles: <jwt.roles>

---

## Required Headers

### Content type

Content-Type: application/json

### Correlation ID
* Client **may provide** `X-Correlation-Id`
* If missing, server generates: `corr_<uuid>`
* Always echoed in response headers

Example:

X-Correlation-Id: corr_abc123

### API Version
X-API-Version: 1


If unsupported → `400 INVALID_FIELD_VALUE`.

---

## Endpoints Summary

### Health
* `GET /health` ✅ canonical

### Resume Evaluation
* `POST /v1/orchestrator/evaluate-cvresume` ✅ primary

### Deprecated Alias (Core Evaluation Service)
* `POST /evaluation/final-resume-score` ⚠️ legacy internal endpoint

---

## 1) Health Endpoint

### GET /health

**Response: 200 OK**

```json
{
  "status": "ok",
  "service": "resume_evaluation_orchestrator",
  "environment": "dev"
}
```

---

## 2) Create CV Generation (REST)
### POST /v1/orchestrator/evaluate-cvresume
Executes a full resume evaluation by:
* validating request payload
* normalizing resume structure
* optionally validating role against official taxonomy
* invoking the LLM evaluation pipeline
* aggregating section-level and global scores
* returning a stable evaluation result

---

### Status Codes
* `200 OK` - evaluation successful
* `400 Bad Request` - validation error / invalid API version
* `404 Not Found` - referenced role not found (if provided)
* `500 Internal Server Error` - unexpected failure

---

## Request Schema
Design Note - Input Sources

The Orchestrator supports multiple upstream sources:
* Frontend / Dev Team
* E-Portfolio Generation Service

Therefore, the API accepts a fully structured resume object directly.
No database fetch is required to evaluate resume content.
Optional role validation may occur if `targetRole` is provided.

### Example (snake_case)
```json
{
  "resume": {
    "contact_information": {
      "name": "Juan Jose Carin",
      "email": "juanjose.carin@gmail.com"
    },
    "professional_summary": {
      "summary_points": [
        "Passionate about data analysis and experiments.",
        "Solid background in data science and statistics."
      ]
    },
    "education": [
      {
        "institution": "University of California, Berkeley",
        "degree": "Master of Information and Data Science",
        "dates": "2016",
        "gpa": "3.93"
      }
    ],
    "experience": [
      {
        "title": "Data Scientist",
        "company": "CONENTO",
        "dates": "Jan 2016 - Mar 2016",
        "description": [
          "Designed and implemented ETL pipelines."
        ]
      }
    ],
    "skills": {
      "technical": ["Data Analysis", "Machine Learning"]
    }
  },
  "target_role": "data_science",
  "language": "en"
}
```

### example (camelCase)
```json
{
  "resume": {
    "contactInformation": {
      "name": "Juan Jose Carin",
      "email": "juanjose.carin@gmail.com"
    },
    "professionalSummary": {
      "summaryPoints": [
        "Passionate about data analysis and experiments.",
        "Solid background in data science and statistics."
      ]
    },
    "education": [
      {
        "institution": "University of California, Berkeley",
        "degree": "Master of Information and Data Science",
        "dates": "2016",
        "gpa": "3.93"
      }
    ],
    "experience": [
      {
        "title": "Data Scientist",
        "company": "CONENTO",
        "dates": "Jan 2016 - Mar 2016",
        "description": [
          "Designed and implemented ETL pipelines."
        ]
      }
    ],
    "skills": {
      "technical": ["Data Analysis", "Machine Learning"]
    }
  },
  "targetRole": "data_science",
  "language": "en"
}
```

### Field Definitions
| Field      | Type   | Required  | Notes                                  |
| ---------- | ------ | --------  | -------------------------------------- |
| resume     | object | ✅        | Structured resume content              |
| targetRole | string | ✅        | Role for relevance validation (default: Data Scientist)|
| language   | enum   | ❌        | en, th (default: en)                   |

---

## Successful Response

**200 OK**

Headers : 
* X-Correlation-Id: corr_...
* X-API-Version: 1

### Response Body
```json
{
  "response": {
    "conclusion": {
      "finalResumeScore": 24.6,
      "sectionContribution": {
        "Profile": {
          "sectionTotal": 16,
          "sectionWeight": 0.1,
          "contribution": 1.6
        }
      }
    },
    "sectionDetail": {
      "Profile": {
        "totalScore": 16,
        "scores": {
          "Completeness": {
            "score": 10,
            "feedback": "Clear professional identity."
          }
        }
      }
    },
    "metadata": {
      "modelName": "gemini-2.5-flash",
      "timestamp": "2025-12-19T15:37:09+07:00",
      "weightsVersion": "weights_v1",
      "promptVersion": "prompt_v2"
    }
  },
  "responseTime": "55.40s"
}
```
---
### Standard Error format
All errors follow this schema:
```json
{
  "code": "VALIDATION_FAILED",
  "message": "Validation failed",
  "subErrors": [
    {
      "field": "resume",
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
### Enumerations
language
* en
* th
---

## Internal Dependencies
### Resume Evaluation Pipeline
* PromptBuilder (YAML-driven)
* LLMCaller (Gemini)
* Section Score Aggregator
* Global Aggregator

### Role validation (Optional)
If targetRole is provided:
* Role may be validated against an official taxonomy (future BigQuery)
* If role is invalid → 404 Not Found

---
## Change Log
* 2025-12-19: Initial Resume Evaluation Orchestrator API specification
* 2025-12-19: Defined structured resume input contract
* 2025-12-19: Added optional role validation support
* 2025-12-19: Standardized evaluation response schema