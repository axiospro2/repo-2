"""Testes da configuração por ambiente (fail-fast via pydantic-settings)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.settings import Settings

_AUTH_KWARGS = {
    "auth_token_url": "https://auth.example.com/token",
    "auth_client_id": "client-id",
    "auth_client_secret": "client-secret",
}


class TestCamposObrigatorios:
    """auth_token_url/auth_client_id/auth_client_secret são obrigatórios."""

    def test_falha_sem_auth_token_url(self):
        with pytest.raises(ValidationError):
            Settings(**{**_AUTH_KWARGS, "auth_token_url": ""}, api_dns="x.com")

    def test_falha_sem_auth_client_id(self):
        with pytest.raises(ValidationError):
            Settings(**{**_AUTH_KWARGS, "auth_client_id": ""}, api_dns="x.com")

    def test_falha_sem_auth_client_secret(self):
        with pytest.raises(ValidationError):
            Settings(**{**_AUTH_KWARGS, "auth_client_secret": ""}, api_dns="x.com")

    def test_sucesso_com_todos_os_campos(self):
        settings = Settings(**_AUTH_KWARGS, api_dns="x.com")
        assert settings.auth_token_url == _AUTH_KWARGS["auth_token_url"]


class TestUrlBaseApiInterna:
    """Resolução de internal_api_base_url a partir de api_dns ou direta."""

    def test_prioriza_url_direta_quando_definida(self):
        settings = Settings(
            **_AUTH_KWARGS,
            internal_api_base_url="https://direta.com/api/",
            api_dns="ignorado.com",
        )
        assert settings.internal_api_base_url == "https://direta.com/api"

    def test_constroi_a_partir_de_api_dns(self):
        settings = Settings(**_AUTH_KWARGS, api_dns="meuambiente.com")
        assert settings.internal_api_base_url == (
            "https://irb-cra-faturamento.meuambiente.com/irb-cra-faturamento/v1"
        )

    def test_falha_sem_url_direta_e_sem_api_dns(self):
        with pytest.raises(ValidationError, match="INTERNAL_API_BASE_URL ou API_DNS"):
            Settings(**_AUTH_KWARGS, api_dns="", internal_api_base_url="")

    def test_normaliza_barra_final_do_path(self):
        settings = Settings(
            **_AUTH_KWARGS, api_dns="x.com", internal_api_path="custom/path/",
        )
        assert settings.internal_api_base_url.endswith("/custom/path")


class TestValoresPadrao:
    """Defaults dos campos não obrigatórios."""

    def test_defaults(self):
        settings = Settings(**_AUTH_KWARGS, api_dns="x.com")
        assert settings.internal_api_path == "irb-cra-faturamento/v1"
        assert settings.integ_timeout_s == 27.0
        assert settings.cors_allow_origin == "*"
        assert settings.quickconfig_app_name == "Faturamento-irb-lambda"
        assert settings.quickconfig_ttl_s == 300
        assert settings.quickconfig_key_faixas == "catalogo-faixas"
        assert settings.quickconfig_key_moedas == "catalogo-moedas"
        assert settings.itau_api_key == ""

    def test_integ_timeout_s_aceita_override_por_env(self, monkeypatch):
        monkeypatch.setenv("INTEG_TIMEOUT_S", "5.5")
        settings = Settings(**_AUTH_KWARGS, api_dns="x.com")
        assert settings.integ_timeout_s == 5.5

    def test_itau_api_key_aceita_override_por_env(self, monkeypatch):
        monkeypatch.setenv("ITAU_API_KEY", "chave-real")
        settings = Settings(**_AUTH_KWARGS, api_dns="x.com")
        assert settings.itau_api_key == "chave-real"
