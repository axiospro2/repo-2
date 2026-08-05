"""Configuração por ambiente (12-factor). Lida uma vez no cold start.

Uma Lambda, dois caminhos:
  - SALVAR: valida contra o serviço de parâmetros (faixas/moedas/gate de divergência).
  - BUSCAR: read-through via NJ6 (hierarquia) + Endpoint de Faturamento (fallback) + catálogo.

Não há troca de implementação em tempo de execução (nenhum "modo mock" dentro do
código da Lambda): local, `NJ6_BASE_URL`/`ENDPOINT_BASE_URL`/`TOKEN_URL` simplesmente
apontam para o stack de mocks subido via `docker-compose` (ver `SETUP.md`); em
produção, apontam para os serviços reais do Itaú. O código dos adapters (`HttpNJ6`,
`HttpEndpoint`) é o mesmo nos dois casos — só a URL muda.

O serviço de parâmetros é diferente: não é REST, é o QuickConfig (biblioteca interna
`manager`, cluster próprio — não um endpoint HTTP com URL). `ParametrosClient`/
`ParametrosCatalogo` (`adapters/parametros.py`) conectam direto no cluster via
`QUICKCONFIG_CLUSTER_MEMBERS`; sem essa variável configurada (ex.: local, sem cluster
disponível), caem no fallback hardcoded do próprio adapter — não tem mock HTTP
equivalente pro QuickConfig.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    tabela_faturamento: str = os.environ.get("TABELA_FATURAMENTO", "tbcv4163_fatm_cogl_subg")

    # RACF de quem informou (responsabilização) chega SEMPRE neste header no POST.
    racf_header: str = os.environ.get("RACF_HEADER", "X-RACF")

    # Integrações de leitura — URLs apontam para mocks (local) ou serviços reais (produção).
    nj6_base_url: str = os.environ.get("NJ6_BASE_URL", "").rstrip("/")
    endpoint_base_url: str = os.environ.get("ENDPOINT_BASE_URL", "").rstrip("/")
    integ_timeout_s: float = float(os.environ.get("INTEG_TIMEOUT_S", "5"))

    # Retry genérico (tenacity) das integrações HTTP (NJ6/Endpoint) — nome herdado de
    # quando o serviço de parâmetros também era HTTP; hoje é usado por `core/retry.py`
    # para qualquer chamada decorada com `@http_retry`, não só parâmetros.
    parametros_retries: int = int(os.environ.get("PARAMETROS_RETRIES", "3"))

    # Serviço de parâmetros — QuickConfig (biblioteca interna `manager`), não REST.
    # Salvar usa faixas/moedas/limite de divergência; buscar só faixas/moedas (catálogo).
    quickconfig_cluster_members: str = os.environ.get("QUICKCONFIG_CLUSTER_MEMBERS", "")
    quickconfig_app_name: str = os.environ.get("QUICKCONFIG_APP_NAME", "Faturamento-irb-lambda")
    quickconfig_ttl_s: int = int(os.environ.get("QUICKCONFIG_TTL_S", "300"))
    quickconfig_key_faixas: str = os.environ.get("QUICKCONFIG_KEY_FAIXAS", "catalogo-faixas")
    quickconfig_key_moedas: str = os.environ.get("QUICKCONFIG_KEY_MOEDAS", "catalogo-moedas")
    quickconfig_key_auditorias: str = os.environ.get(
        "QUICKCONFIG_KEY_AUDITORIAS", "catalogo-auditorias"
    )
    quickconfig_key_limite_divergencia: str = os.environ.get(
        "QUICKCONFIG_KEY_LIMITE_DIVERGENCIA", "limite-Maximo-Divergencia-Porcentagem"
    )

    # ───────── Auth M2M (JWT client_credentials) das chamadas externas ─────────
    # Fluxo: POST no endpoint de token com client_id+secret → access_token (JWT) → as chamadas
    # a NJ6/Endpoint/Parâmetros mandam Authorization: Bearer <token>. Sem TOKEN_URL = mock:
    # gera um JWT fake (sem rede). Para produção, basta setar TOKEN_URL (trocar só a URL).
    # Credenciais (client_id/secret) virão via env, preenchidas pelo Terraform a partir do Secrets Manager.
    token_url: str = os.environ.get("TOKEN_URL", "").rstrip("/")
    token_ttl_margem_s: int = int(os.environ.get("TOKEN_TTL_MARGEM_S", "30"))
    token_timeout_s: float = float(os.environ.get("TOKEN_TIMEOUT_S", "3"))
    auth_client_id: str = os.environ.get(
        "AUTH_CLIENT_ID", os.environ.get("PARAMETROS_CLIENT_ID", "")
    )
    auth_client_secret: str = os.environ.get(
        "AUTH_CLIENT_SECRET", os.environ.get("PARAMETROS_CLIENT_SECRET", "")
    )

    # ───────── Headers customizados do Itaú, usados por todas as chamadas HTTP externas ─────────
    itau_api_key: str = os.environ.get("ITAU_API_KEY", "")
    itau_correlation_id: str = os.environ.get("ITAU_CORRELATION_ID", "")
    itau_flow_id: str = os.environ.get("ITAU_FLOW_ID", "")


settings = Settings()
