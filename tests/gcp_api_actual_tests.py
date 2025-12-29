# tests/gcp_api_actual_tests.py
"""
GCP integration tests for CVResume_evaluation_orchestrator.

⚠️ REQUIREMENTS
- Orchestrator API must be deployed on Cloud Run and reachable:
    https://cvresume-eval-orchestrator-<PROJECT_NUMBER>.<REGION>.run.app

These tests make REAL HTTP calls to the deployed service.
They are intentionally NOT mocked and NOT meant for CI.

WHAT IT DOES
- GET /health (Cloud Run deployment uses /health, not /healthz)
- Loads every JSON payload in: tests/test_payloads/*.json
- POSTs each payload to: /api/v1/resume-evaluations
- Prints response (status + x-headers + body)
- Asserts response contract (success OR standardized error)
- Supports soft-failing known transient downstream failures (timeouts)

RECOMMENDED USAGE
- Run as a script (best):
    python tests/gcp_api_actual_tests.py

- Or run via pytest explicitly (NOT for CI):
    pytest -q tests/gcp_api_actual_tests.py -s

CONFIG
- Set BASE_URL via env var (recommended):
    export CVRESUME_GCP_BASE_URL="https://cvresume-eval-orchestrator-....run.app"

If not set, the default BASE_URL below will be used (edit to your service URL).
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx


# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------
DEFAULT_BASE_URL = "https://cvresume-eval-orchestrator-810737581373.asia-southeast1.run.app"
BASE_URL = os.getenv("CVRESUME_GCP_BASE_URL", DEFAULT_BASE_URL).rstrip("/")

HEADERS = {"Content-Type": "application/json"}

THIS_DIR = Path(__file__).resolve().parent
PAYLOAD_DIR = THIS_DIR / "test_payloads"

CORRELATION_HEADER = "X-Correlation-Id"
API_VERSION_HEADER = "X-API-Version"


# ---------------------------------------------------------------------
# Expectations / result typing
# ---------------------------------------------------------------------
@dataclass(frozen=True)
class Expectation:
    """
    Per-payload test expectations.

    - allow_failure: if True, failures do not fail the whole suite
    - expected_status: if set, assert exact HTTP status (e.g., 200 or 502)
    - allow_transient_downstream_timeouts: if True, treat downstream timeouts as soft-fail
    """
    allow_failure: bool = False
    expected_status: Optional[int] = None
    allow_transient_downstream_timeouts: bool = True


def pretty(resp: httpx.Response) -> None:
    print(f"\nSTATUS: {resp.status_code}")
    print("HEADERS:")
    for k, v in resp.headers.items():
        if k.lower().startswith("x-"):
            print(f"  {k}: {v}")
    try:
        print("BODY:")
        print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
    except Exception:
        print(resp.text)


def _load_payload_files() -> List[Path]:
    if not PAYLOAD_DIR.exists():
        raise FileNotFoundError(f"Payload directory not found: {PAYLOAD_DIR}")

    files = sorted(PAYLOAD_DIR.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"No payload JSON files found in: {PAYLOAD_DIR}/*.json")

    return files


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise TypeError(f"Payload must be a JSON object (dict). Got: {type(data)} in {path.name}")
    return data


def _extract_expectation(payload: Dict[str, Any], filename: str) -> Expectation:
    """
    Two ways to specify expected behavior:

    A) Filename convention (simple):
       - *_allow_fail.json  => allow_failure=True

    B) Inline metadata in JSON (explicit):
       {
         "__expect": {
           "allow_failure": true,
           "expected_status": 200,
           "allow_transient_downstream_timeouts": false
         },
         ... real payload fields ...
       }

    The "__expect" key is removed before sending the payload.
    """
    allow_failure = filename.endswith("_allow_fail.json")

    expect_obj = payload.pop("__expect", None)
    if isinstance(expect_obj, dict):
        allow_failure = bool(expect_obj.get("allow_failure", allow_failure))
        expected_status = expect_obj.get("expected_status")
        if expected_status is not None:
            expected_status = int(expected_status)

        allow_timeouts = bool(expect_obj.get("allow_transient_downstream_timeouts", True))

        return Expectation(
            allow_failure=allow_failure,
            expected_status=expected_status,
            allow_transient_downstream_timeouts=allow_timeouts,
        )

    return Expectation(allow_failure=allow_failure)


def _post_resume_evaluation(payload: Dict[str, Any], *, correlation_id: str, timeout: float = 180.0) -> httpx.Response:
    headers = dict(HEADERS)
    headers[CORRELATION_HEADER] = correlation_id

    return httpx.post(
        f"{BASE_URL}/api/v1/resume-evaluations",
        headers=headers,
        json=payload,
        timeout=timeout,
    )


# ---------------------------------------------------------------------
# Contract checks
# ---------------------------------------------------------------------
def _assert_success_contract(body: Dict[str, Any]) -> float:
    # On HTTP < 400, status must be "success"
    assert body.get("status") == "success", f"unexpected status={body.get('status')}"

    assert "data" in body and isinstance(body["data"], dict), "missing/invalid data"
    assert "conclusion" in body["data"], "missing data.conclusion"

    # section detail may be camelCase or preserved snake_case
    assert "sectionDetail" in body["data"] or "section_detail" in body["data"], (
        "missing section detail (expected sectionDetail or section_detail)"
    )

    conclusion = body["data"]["conclusion"]

    # IMPORTANT:
    # Do NOT use `or` here because 0.0 is a valid score but falsy.
    score = conclusion.get("finalResumeScore", None)
    if score is None:
        score = conclusion.get("final_resume_score", None)
    if score is None:
        score = conclusion.get("final_score", None)

    assert score is not None, "missing final score (finalResumeScore/final_resume_score/final_score)"

    if isinstance(score, str):
        return float(score)
    if isinstance(score, (int, float)):
        return float(score)

    raise AssertionError(f"final score has unexpected type: {type(score)}")


def _assert_error_contract(body: Dict[str, Any]) -> None:
    # Standard error schema
    assert isinstance(body.get("code"), str) and body["code"], "missing error code"
    assert isinstance(body.get("message"), str) and body["message"], "missing error message"
    assert "subErrors" in body and isinstance(body["subErrors"], list), "missing/invalid subErrors"
    assert "correlationId" in body or "correlation_id" in body, "missing correlation id in error body"


def _is_transient_downstream_timeout(resp: httpx.Response) -> bool:
    """
    Detect known transient downstream timeout pattern:
      HTTP 502
      body.code in (BAD_GATEWAY, SERVICE_UNAVAILABLE, HTTP_ERROR)
      message contains 'Read timed out' or 'timed out'
      subErrors[].errors[].code == EVALUATOR_CALL_FAILED
    """
    try:
        body = resp.json()
    except Exception:
        return False

    if resp.status_code != 502:
        return False

    if body.get("code") not in ("BAD_GATEWAY", "SERVICE_UNAVAILABLE", "HTTP_ERROR"):
        return False

    msg = str(body.get("message", ""))
    if "Read timed out" not in msg and "timed out" not in msg.lower():
        return False

    sub_errors = body.get("subErrors") or []
    for se in sub_errors:
        errs = se.get("errors") if isinstance(se, dict) else None
        if not isinstance(errs, list):
            continue
        for e in errs:
            if isinstance(e, dict) and e.get("code") == "EVALUATOR_CALL_FAILED":
                return True

    return False


# ---------------------------------------------------------------------
# 1) Health check (GCP uses /health; /healthz may not exist)
# ---------------------------------------------------------------------
def test_health() -> None:
    print("\n=== TEST 1: GET /health ===")
    resp = httpx.get(f"{BASE_URL}/health", timeout=10)
    pretty(resp)

    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"

    # Optional but useful signals on Cloud Run
    api_ver = resp.headers.get(API_VERSION_HEADER)
    corr = resp.headers.get(CORRELATION_HEADER)
    assert api_ver is not None and api_ver != "", "missing X-API-Version header"
    assert corr is not None and corr != "", "missing X-Correlation-Id header"


# ---------------------------------------------------------------------
# 2) Run all payloads in tests/test_payloads
# ---------------------------------------------------------------------
def test_all_payloads_in_test_payloads_dir() -> None:
    print("\n=== TEST 2: POST /api/v1/resume-evaluations for all payloads in tests/test_payloads ===")
    print(f"BASE_URL = {BASE_URL}")

    files = _load_payload_files()
    print(f"Found {len(files)} payload file(s) in {PAYLOAD_DIR}")

    passed: List[str] = []
    soft_failed: List[str] = []
    hard_failed: List[str] = []
    scores: List[Tuple[str, float]] = []

    for idx, path in enumerate(files, start=1):
        print("\n" + "-" * 78)
        print(f"[{idx}/{len(files)}] PAYLOAD: {path.name}")

        payload = _load_json(path)
        expect = _extract_expectation(payload, path.name)

        correlation_id = f"corr-gcp-payload-{path.stem}-{int(time.time())}"

        try:
            resp = _post_resume_evaluation(payload, correlation_id=correlation_id)
            pretty(resp)

            # If caller pins an expected status, enforce it.
            if expect.expected_status is not None:
                assert resp.status_code == expect.expected_status, (
                    f"{path.name}: expected {expect.expected_status} but got {resp.status_code}"
                )

            # Success path
            if resp.status_code < 400:
                body = resp.json()
                score = _assert_success_contract(body)

                # correlation id must exist either in body or header
                body_corr = body.get("correlationId") or body.get("correlation_id")
                header_corr = resp.headers.get(CORRELATION_HEADER)
                assert body_corr or header_corr, f"{path.name}: missing correlation id in body and headers"

                passed.append(path.name)
                scores.append((path.name, score))
                continue

            # Error path (must follow your standard error contract)
            err_body = resp.json()
            _assert_error_contract(err_body)

            # Allow transient downstream timeout as soft-fail (default)
            if expect.allow_transient_downstream_timeouts and _is_transient_downstream_timeout(resp):
                soft_failed.append(f"{path.name}: transient downstream timeout (treated as soft-fail)")
                continue

            # If this payload is marked allow_failure, treat as soft-fail
            if expect.allow_failure:
                soft_failed.append(f"{path.name}: error status {resp.status_code} (allow_failure=True)")
                continue

            # Otherwise hard fail
            hard_failed.append(f"{path.name}: expected success but got {resp.status_code}")

        except Exception as exc:
            if expect.allow_failure:
                soft_failed.append(f"{path.name}: exception (allow_failure=True): {exc}")
            else:
                hard_failed.append(f"{path.name}: exception: {exc}")

    print("\n" + "=" * 78)
    print("SUMMARY")
    print(f"  Total payloads: {len(files)}")
    print(f"  Passed: {len(passed)}")
    print(f"  Soft-failed: {len(soft_failed)}")
    print(f"  Hard-failed: {len(hard_failed)}")

    if scores:
        print("\nSCORES (file -> final_score):")
        for name, score in scores:
            print(f"  - {name}: {score}")

    if soft_failed:
        print("\nSOFT FAILURES (non-deterministic / allowed):")
        for msg in soft_failed:
            print(f"  - {msg}")

    if hard_failed:
        print("\nHARD FAILURES:")
        for msg in hard_failed:
            print(f"  - {msg}")
        raise AssertionError(f"{len(hard_failed)} hard failure(s) occurred")


# ---------------------------------------------------------------------
# Entry point (run as script)
# ---------------------------------------------------------------------
if __name__ == "__main__":
    try:
        test_health()
        test_all_payloads_in_test_payloads_dir()
    except AssertionError:
        print("\nTEST FAILED")
        raise
    except Exception as e:
        print("\nERROR:", e)
        sys.exit(1)

    print("\nALL GCP API PAYLOAD TESTS PASSED ✅")
