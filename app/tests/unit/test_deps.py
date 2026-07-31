from types import SimpleNamespace

from app.api import deps


def _fake_settings(**overrides) -> SimpleNamespace:
    base = dict(
        token_url="http://mock/token-deps",
        auth_client_id="cid",
        auth_client_secret="secret",
        itau_api_key="",
        itau_correlation_id="",
        itau_flow_id="",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_deps_sao_singletons_cacheados(monkeypatch):
    monkeypatch.setattr("app.adapters.auth.settings", _fake_settings())

    funcoes = (
        deps.get_token_provider,
        deps.get_repo,
        deps.get_parametros,
        deps.get_nj6,
        deps.get_endpoint,
        deps.get_catalogo,
    )
    for fn in funcoes:
        fn.cache_clear()

    try:
        for fn in funcoes:
            assert fn() is fn()
    finally:
        for fn in funcoes:
            fn.cache_clear()
