"""Configuração por ambiente do BFF."""
from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PATH_API_INTERNA_PADRAO = "irb-cra-faturamento/v1"


class Settings(BaseSettings):
    """Configuração validada na inicialização (fail-fast).

    `auth_token_url`/`auth_client_id`/`auth_client_secret` são obrigatórios:
    gerar e anexar o token OAuth2 é a função central deste BFF, então subir
    sem essas credenciais é um erro de configuração, não um modo válido.
    """

    model_config = SettingsConfigDict(extra="ignore")

    # DNS e path da API interna – usados para montar a URL quando
    # INTERNAL_API_BASE_URL não vier definida diretamente.
    api_dns: str = ""
    internal_api_path: str = _PATH_API_INTERNA_PADRAO
    internal_api_base_url: str = ""

    integ_timeout_s: float = 27.0
    cors_allow_origin: str = "*"

    # QuickConfig - catálogo de parâmetros
    quickconfig_cluster_members: str = ""
    quickconfig_app_name: str = "Faturamento-irb-lambda"
    quickconfig_ttl_s: int = 300
    quickconfig_key_faixas: str = "catalogo-faixas"
    quickconfig_key_moedas: str = "catalogo-moedas"

    # OAuth2 para autenticação M2M com a API interna (obrigatório)
    auth_token_url: str = Field(min_length=1)
    auth_client_id: str = Field(min_length=1)
    auth_client_secret: str = Field(min_length=1)

    @model_validator(mode="after")
    def _resolver_url_base_api_interna(self) -> "Settings":
        self.internal_api_path = self.internal_api_path.rstrip("/")

        if self.internal_api_base_url:
            self.internal_api_base_url = self.internal_api_base_url.rstrip("/")
            return self

        if self.api_dns:
            dns = self.api_dns.rstrip("/")
            self.internal_api_base_url = (
                f"https://irb-cra-faturamento.{dns}/{self.internal_api_path}"
            )
            return self

        raise ValueError(
            "Defina INTERNAL_API_BASE_URL ou API_DNS: o BFF precisa saber "
            "para onde encaminhar as requisições."
        )


settings = Settings()
