# tests/test_data_fetcher.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import pytest
import functions.orchestrator.data_fetcher as df_mod

@pytest.fixture
def anyio_backend():
    return "asyncio"

@dataclass
class _FakeSettings:
    data_api_base_url: str = "https://example-data-api"
    http_timeout_seconds: int = 15
    max_retries: int = 0  # keep test fast (attempts = max_retries + 1)


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self._payload = payload
        self.text = ""  # used for snippet

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeAsyncClient:
    """
    Mimics httpx.AsyncClient used as:
      async with httpx.AsyncClient(timeout=...) as client:
          resp = await client.get(url)
    """
    def __init__(self, *, timeout: Any):
        self.timeout = timeout
        self.calls: list[str] = []

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, url: str) -> _FakeResponse:
        self.calls.append(url)
        # default OK response — can be overridden per test via monkeypatch
        return _FakeResponse(200, {"data": {"role_title": "AI Engineer"}})


@pytest.mark.anyio
async def test_fetch_role_core_url_encodes_role_id_and_uses_config_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 1) Force endpoint template config (avoid reading config.yaml)
    df_mod.load_orchestrator_config.cache_clear()
    monkeypatch.setattr(
        df_mod,
        "load_orchestrator_config",
        lambda: {"data_api": {"endpoints": {"role_core": "/v1/roles/{role_id}/core"}}},
    )

    # 2) Patch httpx.AsyncClient to our fake client
    fake_client = _FakeAsyncClient(timeout=15)

    # We need factory so DataFetcher creates a new client inside _get_json
    def _client_factory(*, timeout: Any):
        # return the same instance so we can inspect calls
        fake_client.timeout = timeout
        return fake_client

    monkeypatch.setattr(df_mod.httpx, "AsyncClient", _client_factory)

    fetcher = df_mod.DataFetcher(_FakeSettings())  # type: ignore[arg-type]

    role_id = "role#ai_engineer"
    out = await fetcher.fetch_role_core(role_id)

    # URL encoding check
    assert fake_client.calls, "Expected at least one GET call"
    called_url = fake_client.calls[0]
    assert called_url == "https://example-data-api/v1/roles/role%23ai_engineer/core"

    # Wrapper normalization check: {"data": {...}} -> {...}
    assert out == {"role_title": "AI Engineer"}


@pytest.mark.anyio
async def test_fetch_role_core_returns_raw_dict_if_not_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    df_mod.load_orchestrator_config.cache_clear()
    monkeypatch.setattr(
        df_mod,
        "load_orchestrator_config",
        lambda: {"data_api": {"endpoints": {"role_core": "/v1/roles/{role_id}/core"}}},
    )

    class _Client(_FakeAsyncClient):
        async def get(self, url: str) -> _FakeResponse:
            self.calls.append(url)
            return _FakeResponse(200, {"role_title": "AI Engineer"})  # not wrapped

    fake_client = _Client(timeout=15)

    monkeypatch.setattr(df_mod.httpx, "AsyncClient", lambda *, timeout: fake_client)

    fetcher = df_mod.DataFetcher(_FakeSettings())  # type: ignore[arg-type]
    out = await fetcher.fetch_role_core("role#ai_engineer")

    assert out == {"role_title": "AI Engineer"}


@pytest.mark.anyio
async def test_get_endpoint_template_missing_raises_runtimeerror(monkeypatch: pytest.MonkeyPatch) -> None:
    df_mod.load_orchestrator_config.cache_clear()
    monkeypatch.setattr(df_mod, "load_orchestrator_config", lambda: {})  # no endpoints

    fetcher = df_mod.DataFetcher(_FakeSettings())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError):
        await fetcher.fetch_role_core("role#ai_engineer")
