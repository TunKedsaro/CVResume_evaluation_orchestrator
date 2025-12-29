# tests/test_resume_evaluations_endpoint.py
from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

import api  # imports app + module-level objects


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """
    Build TestClient after patching settings-dependent objects if needed.
    If your api.py initializes fetcher/svc at import-time, we will monkeypatch them in tests directly.
    """
    return TestClient(api.app)


def test_health_ok(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "service" in body


def test_healthz_ok(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"


def test_post_resume_evaluations_success_role_id_resolution_and_camelcase(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # --- Arrange: role_id -> role_name from Data API ---
    async def fake_fetch_role_core(role_id: str):
        assert role_id == "role#ds"
        return {"role_name": "data scientist"}

    monkeypatch.setattr(api.fetcher, "fetch_role_core", fake_fetch_role_core)

    # --- Arrange: evaluator call ---
    # NOTE: api passes role_context, so mock must accept it (or **kwargs).
    def fake_evaluate(*, resume_json, target_role, output_lang, correlation_id, **kwargs):
        role_context = kwargs.get("role_context")
        assert role_context is None or isinstance(role_context, str)

        assert isinstance(resume_json, dict)
        assert target_role == "data scientist"  # resolved name
        assert output_lang in ("en", "th")
        assert correlation_id == "corr-123"

        return {
            "conclusion": {
                "final_resume_score": 25.0,
                "section_contribution": {
                    "Profile": {"section_total": 16.0, "section_weight": 0.1, "contribution": 1.6}
                },
            },
            "section_detail": {
                "Profile": {
                    "total_score": 16.0,
                    "scores": {
                        "Completeness": {"score": 10, "feedback": "..."},
                        "ContentQuality": {"score": 6, "feedback": "..."},
                    },
                }
            },
            "correlation_id": "corr-123",
        }

    monkeypatch.setattr(api, "svc", type("SVC", (), {"evaluate": staticmethod(fake_evaluate)})())

    payload = {
        "resume_json": {"experience": [], "education": [], "skills": {}},
        "target_role": "role#ds",  # <-- treated as role_id
        "output_lang": "en",
    }

    # --- Act ---
    r = client.post(
        "/api/v1/resume-evaluations",
        json=payload,
        headers={"X-Correlation-Id": "corr-123"},
    )

    # --- Assert ---
    assert r.status_code == 200
    body = r.json()

    # New contract
    assert body["status"] == "success"
    assert body["correlationId"] == "corr-123"

    # Middleware headers should be present
    assert r.headers.get("X-Correlation-Id") == "corr-123"
    assert r.headers.get("X-API-Version") == "1"

    # camelCase boundary
    assert "data" in body
    assert body["data"]["conclusion"]["finalResumeScore"] == 25.0
    assert "sectionContribution" in body["data"]["conclusion"]
    assert "sectionDetail" in body["data"]


def test_post_resume_evaluations_default_output_lang_when_none(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch_role_core(role_id: str):
        return {"role_name": "data scientist"}

    monkeypatch.setattr(api.fetcher, "fetch_role_core", fake_fetch_role_core)

    # NOTE: api passes role_context, so mock must accept it (or **kwargs).
    def fake_evaluate(*, resume_json, target_role, output_lang, correlation_id, **kwargs):
        role_context = kwargs.get("role_context")
        assert role_context is None or isinstance(role_context, str)

        assert output_lang == "en"
        return {
            "conclusion": {"final_resume_score": 10.0, "section_contribution": {}},
            "section_detail": {},
            "correlation_id": correlation_id or "generated",
        }

    monkeypatch.setattr(api, "svc", type("SVC", (), {"evaluate": staticmethod(fake_evaluate)})())

    payload = {
        "resume_json": {"experience": []},
        "target_role": "role#ds",
        # output_lang omitted
    }

    r = client.post("/api/v1/resume-evaluations", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert body["data"]["conclusion"]["finalResumeScore"] == 10.0
    assert r.headers.get("X-API-Version") == "1"


def test_post_resume_evaluations_role_resolution_failure_returns_502(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch_role_core(role_id: str):
        raise RuntimeError("Data API down")

    monkeypatch.setattr(api.fetcher, "fetch_role_core", fake_fetch_role_core)

    payload = {"resume_json": {"experience": []}, "target_role": "role#ds"}

    r = client.post("/api/v1/resume-evaluations", json=payload)
    assert r.status_code == 502

    body = r.json()
    # Standard error format (from your middleware/handlers)
    assert body["code"] in ("BAD_GATEWAY", "SERVICE_UNAVAILABLE", "HTTP_ERROR")
    assert "Data API" in body["message"] or "down" in body["message"]

    # Headers still present (middleware)
    assert r.headers.get("X-API-Version") == "1"
    assert "X-Correlation-Id" in r.headers


def test_post_resume_evaluations_failure_returns_502(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch_role_core(role_id: str):
        return {"role_name": "data scientist"}

    monkeypatch.setattr(api.fetcher, "fetch_role_core", fake_fetch_role_core)

    def fake_evaluate(*args, **kwargs):
        raise RuntimeError("Evaluator returned non-JSON (status=500)")

    monkeypatch.setattr(api, "svc", type("SVC", (), {"evaluate": staticmethod(fake_evaluate)})())

    payload = {"resume_json": {"experience": []}, "target_role": "role#ds"}

    r = client.post("/api/v1/resume-evaluations", json=payload)
    assert r.status_code == 502

    body = r.json()
    # Standard error format
    assert body["code"] in ("BAD_GATEWAY", "SERVICE_UNAVAILABLE", "HTTP_ERROR")
    assert "Evaluator" in body["message"] or "non-JSON" in body["message"]

    assert r.headers.get("X-API-Version") == "1"
    assert "X-Correlation-Id" in r.headers


def test_post_resume_evaluations_missing_required_fields_returns_400_validation_failed(
    client: TestClient,
) -> None:
    # With your custom RequestValidationError handler, this should be 400 (not 422)
    r = client.post("/api/v1/resume-evaluations", json={})
    assert r.status_code == 400
    body = r.json()
    assert body["code"] == "VALIDATION_FAILED"
    assert isinstance(body["subErrors"], list)

    assert r.headers.get("X-API-Version") == "1"
    assert "X-Correlation-Id" in r.headers


def test_post_resume_evaluations_final_score_coerces_string_to_float(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch_role_core(role_id: str):
        return {"role_name": "data scientist"}

    monkeypatch.setattr(api.fetcher, "fetch_role_core", fake_fetch_role_core)

    # NOTE: api passes role_context, so mock must accept it (or **kwargs).
    def fake_evaluate(*, resume_json, target_role, output_lang, correlation_id, **kwargs):
        role_context = kwargs.get("role_context")
        assert role_context is None or isinstance(role_context, str)

        return {
            "conclusion": {"final_resume_score": "25.0", "section_contribution": {}},
            "section_detail": {},
            "correlation_id": correlation_id or "x",
        }

    monkeypatch.setattr(api, "svc", type("SVC", (), {"evaluate": staticmethod(fake_evaluate)})())

    payload = {"resume_json": {"experience": []}, "target_role": "role#ds"}
    r = client.post("/api/v1/resume-evaluations", json=payload)

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert body["data"]["conclusion"]["finalResumeScore"] == 25.0
    assert r.headers.get("X-API-Version") == "1"
