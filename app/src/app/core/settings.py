"""Configuração por ambiente (12-factor). Lida uma vez no cold start.

Uma Lambda, dois caminhos:
  - SALVAR: valida contra o serviço de parâmetros (faixas/moedas/gate de divergência).
  - BUSCAR: read-through via NJ6 (hierarquia) + Endpoint de Faturamento (fallback) + catálogo.

`USAR_MOCK_INTEGRACOES=1` (default) usa os mocks de fixture no caminho de leitura; =0 aponta
para os stubs HTTP (que ainda têm TODO de URL/auth — contrato pendente com Deus/Felipe).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _flag(nome: str, default: str = "1") -> bool:
    return os.environ.get(nome, default).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    tabela_faturamento: str = os.environ.get("TABELA_FATURAMENTO", "tbcv4163_fatm_cogl_subg")

    # RACF de quem informou (responsabilização) chega SEMPRE neste header no POST.
    racf_header: str = os.environ.get("RACF_HEADER", "X-RACF")

    # Integrações de leitura (mock por padrão nesta entrega).
    usar_mock_integracoes: bool = _flag("USAR_MOCK_INTEGRACOES", "1")
    nj6_base_url: str = os.environ.get("NJ6_BASE_URL", "").rstrip("/")
    endpoint_base_url: str = os.environ.get("ENDPOINT_BASE_URL", "").rstrip("/")
    integ_timeout_s: float = float(os.environ.get("INTEG_TIMEOUT_S", "5"))

    # Serviço de parâmetros (salvar: gate/faixas/moedas; buscar: catálogo de faixas → rótulo).
    parametros_base_url: str = os.environ.get("PARAMETROS_BASE_URL", "").rstrip("/")
    parametros_ttl_s: int = int(os.environ.get("PARAMETROS_TTL_S", "300"))
    parametros_timeout_s: float = float(os.environ.get("PARAMETROS_TIMEOUT_S", "3"))
    parametros_retries: int = int(os.environ.get("PARAMETROS_RETRIES", "3"))

    # ───────── Auth M2M (JWT client_credentials) das chamadas externas ─────────
    # Fluxo: POST no endpoint de token com client_id+secret → access_token (JWT) → as chamadas
    # a NJ6/Endpoint/Parâmetros mandam Authorization: Bearer <token>. Sem TOKEN_URL = mock:
    # gera um JWT fake (sem rede). Para produção, basta setar TOKEN_URL (trocar só a URL).
    # Credenciais (client_id/secret) virão via env, preenchidas pelo Terraform a partir do Secrets Manager.
    token_url: str = os.environ.get("TOKEN_URL", "").rstrip("/")
    token_ttl_margem_s: int = int(os.environ.get("TOKEN_TTL_MARGEM_S", "30"))
    token_timeout_s: float = float(os.environ.get("TOKEN_TIMEOUT_S", "3"))
    auth_client_id: str = os.environ.get("AUTH_CLIENT_ID", os.environ.get("PARAMETROS_CLIENT_ID", ""))
    auth_client_secret: str = os.environ.get("AUTH_CLIENT_SECRET", os.environ.get("PARAMETROS_CLIENT_SECRET", ""))


settings = Settings()
