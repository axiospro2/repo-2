import json
from types import SimpleNamespace

import pytest

from app.adapters.auth import OAuth2TokenProvider, build_token_provider
from app.core.oauth2 import OAuth2Manager, _token_cache
from tests.http_fakes import FakePool, FakeResponse


def _fake_settings(**overrides) -> SimpleNamespace:
    base = dict(
        token_url="http://mock/token",
        auth_client_id="cid",
        auth_client_secret="secret",
        itau_api_key="",
        itau_correlation_id="",
        itau_flow_id="",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _patch_pool(monkeypatch, pool: FakePool) -> None:
    monkeypatch.setattr("app.core.oauth2.get_pool", lambda *a, **k: pool)


def test_oauth2_token_provider_get_token(monkeypatch):
    pool = FakePool(
        [FakeResponse(200, json.dumps({"access_token": "tok-auth", "expires_in": 100}).encode())]
    )
    _patch_pool(monkeypatch, pool)
    manager = OAuth2Manager(
        token_url="http://mock/token-auth-1", client_id="cid", client_secret="secret"
    )
    provider = OAuth2TokenProvider(manager)

    assert provider.get_token() == "tok-auth"
    _token_cache.pop("http://mock/token-auth-1", None)


def test_oauth2_token_provider_auth_headers(monkeypatch):
    pool = FakePool(
        [FakeResponse(200, json.dumps({"access_token": "tok-auth2", "expires_in": 100}).encode())]
    )
    _patch_pool(monkeypatch, pool)
    manager = OAuth2Manager(
        token_url="http://mock/token-auth-2", client_id="cid", client_secret="secret"
    )
    provider = OAuth2TokenProvider(manager)

    assert provider.auth_headers() == {"Authorization": "Bearer tok-auth2"}
    _token_cache.pop("http://mock/token-auth-2", None)


def test_build_token_provider_exige_token_url(monkeypatch):
    monkeypatch.setattr("app.adapters.auth.settings", _fake_settings(token_url=""))

    with pytest.raises(ValueError):
        build_token_provider()


def test_build_token_provider_exige_client_id(monkeypatch):
    monkeypatch.setattr("app.adapters.auth.settings", _fake_settings(auth_client_id=""))

    with pytest.raises(ValueError):
        build_token_provider()


def test_build_token_provider_exige_client_secret(monkeypatch):
    monkeypatch.setattr("app.adapters.auth.settings", _fake_settings(auth_client_secret=""))

    with pytest.raises(ValueError):
        build_token_provider()


def test_build_token_provider_sucesso(monkeypatch):
    monkeypatch.setattr(
        "app.adapters.auth.settings", _fake_settings(token_url="http://mock/token-build")
    )

    provider = build_token_provider()
    assert isinstance(provider, OAuth2TokenProvider)
