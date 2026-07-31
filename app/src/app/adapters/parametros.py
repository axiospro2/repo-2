"""Clientes do serviço de parâmetros — QuickConfig (biblioteca interna `manager`, não REST).

Dois consumidores, mesma infraestrutura (`_ClienteQuickConfig`):
  - `ParametrosClient` (SALVAR): faixas, moedas e limite de variação (%) do gate de
    divergência. O gate está sempre ativo — existe um limite real configurado no
    QuickConfig (`limite-Maximo-Divergencia-Porcentagem`), não há liga/desliga separado.
  - `ParametrosCatalogo` (BUSCAR): só o catálogo (faixas → rótulo, moedas) — não precisa
    do limite de divergência.

Ambos: cache em memória por TTL (Lambda quente) e log técnico (`parametros.fetch`) com
cache_hit/latência. Em indisponibilidade cada cliente cai no SEU fallback hardcoded — e o
fallback NUNCA é cacheado (tenta de novo na próxima invocação).
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from manager import ConfigurationService, QuickConfigConfigurationSource

from app.core.logging import get_logger, log_event
from app.core.settings import settings

_logger = get_logger("faturamento.parametros")

_FAIXAS_FALLBACK: list[dict] = [
    {"codigo": "FAIXA_1", "descricao": "R$ 360 mil a R$ 4,8 MM", "min": 360000, "max": 4800000},
    {"codigo": "FAIXA_2", "descricao": "R$ 4,8 MM a R$ 20 MM", "min": 4800000, "max": 20000000},
    {"codigo": "FAIXA_3", "descricao": "R$ 20 MM a R$ 100 MM", "min": 20000000, "max": 100000000},
    {"codigo": "FAIXA_4", "descricao": "R$ 100 MM a R$ 500 MM", "min": 100000000, "max": 500000000},
    {"codigo": "FAIXA_5", "descricao": "R$ 500 MM a R$ 2 BI", "min": 500000000, "max": 2000000000},
    {"codigo": "FAIXA_6", "descricao": "Acima de R$ 2 BI", "min": 2000000000, "max": None},
]
_MOEDAS_FALLBACK: list[str] = ["BRL", "USD"]


class _ClienteQuickConfig:
    """Template: conecta no QuickConfig (cache TTL) e devolve o snapshot que a subclasse
    monta a partir das chaves configuradas. Subclasses definem `_buscar`/`_fallback`."""

    def __init__(
        self,
        cluster_members: Optional[str] = None,
        app_name: Optional[str] = None,
        ttl_s: Optional[int] = None,
    ):
        self._cluster_members = (cluster_members or settings.quickconfig_cluster_members).strip()
        self._app_name = app_name or settings.quickconfig_app_name
        self._ttl = ttl_s if ttl_s is not None else settings.quickconfig_ttl_s

        self._cache: Optional[dict] = None
        self._exp: float = 0.0
        self._config_service: Optional[ConfigurationService] = None

    def _inicializar_servico(self) -> ConfigurationService:
        """Inicializa (uma vez) e devolve o ConfigurationService do QuickConfig."""
        if self._config_service is not None:
            return self._config_service

        if not self._cluster_members:
            raise ValueError("QUICKCONFIG_CLUSTER_MEMBERS não está configurado!")

        try:
            log_event(_logger, "quickconfig.conectando", cluster_members=self._cluster_members)
            config_source = QuickConfigConfigurationSource(
                app_name=self._app_name,
                sync=True,
                listener_mode=False,
                cluster_members=self._cluster_members.split(","),
            )
            self._config_service = ConfigurationService(config_source)
            log_event(_logger, "quickconfig.conectado", level="info")
            return self._config_service
        except Exception:
            _logger.exception(
                "quickconfig.erro_conexao", extra={"ctx": {"event": "quickconfig.erro_conexao"}}
            )
            raise

    def obter(self) -> dict:
        """Snapshot de parâmetros (cacheado). Nunca lança — cai no fallback da subclasse."""
        agora = time.time()
        if self._cache is not None and agora < self._exp:
            log_event(_logger, "parametros.fetch", level="debug", cache_hit=True)
            return self._cache

        inicio = time.perf_counter()
        try:
            service = self._inicializar_servico()
            snapshot = self._buscar(service)
        except Exception as e:
            log_event(_logger, "parametros.indisponivel", level="error", erro=str(e))
            return self._fallback()

        self._cache = snapshot
        self._exp = agora + self._ttl
        log_event(
            _logger,
            "parametros.fetch",
            level="debug",
            cache_hit=False,
            latency_ms=round((time.perf_counter() - inicio) * 1000, 1),
            faixas=len(snapshot.get("faixas") or []),
            moedas=len(snapshot.get("moedas") or []),
        )
        return snapshot

    # ───────── pontos de extensão ─────────

    def _buscar(self, service: ConfigurationService) -> dict:
        """Chaves do QuickConfig → snapshot que este cliente expõe."""
        raise NotImplementedError

    def _fallback(self) -> dict:
        """Snapshot degradado quando o QuickConfig está indisponível (não é cacheado)."""
        raise NotImplementedError

    @staticmethod
    def _parse_json(data: Any, default: Any = None) -> Any:
        """Parse seguro de JSON — o QuickConfig devolve string JSON (ou já o objeto)."""
        try:
            if isinstance(data, str):
                return json.loads(data)
            return data if data is not None else default
        except (json.JSONDecodeError, TypeError) as e:
            log_event(_logger, "parametros.parse_json_falhou", level="warning", erro=str(e))
            return default


class ParametrosClient(_ClienteQuickConfig):
    """SALVAR — faixas + moedas + limite de variação (%). Gate sempre ativo."""

    def __init__(
        self,
        cluster_members: Optional[str] = None,
        app_name: Optional[str] = None,
        ttl_s: Optional[int] = None,
        key_faixas: Optional[str] = None,
        key_moedas: Optional[str] = None,
        key_limite_divergencia: Optional[str] = None,
    ):
        super().__init__(cluster_members, app_name, ttl_s)
        self._key_faixas = key_faixas or settings.quickconfig_key_faixas
        self._key_moedas = key_moedas or settings.quickconfig_key_moedas
        self._key_limite_divergencia = (
            key_limite_divergencia or settings.quickconfig_key_limite_divergencia
        )

    def _buscar(self, service: ConfigurationService) -> dict:
        faixas_raw = service.get_config_for_app(self._app_name, self._key_faixas, "[]")
        moedas_raw = service.get_config_for_app(self._app_name, self._key_moedas, "[]")
        limite_raw = service.get_config_for_app(self._app_name, self._key_limite_divergencia, "0")
        return {
            "gateDivergenciaAtivo": True,
            "limiteVariacaoPercentual": int(self._parse_json(limite_raw, 0)),
            "faixas": self._parse_json(faixas_raw, []),
            "moedas": self._parse_json(moedas_raw, []),
        }

    def _fallback(self) -> dict:
        """Mock das faixas quando o QuickConfig está indisponível."""
        return {
            "gateDivergenciaAtivo": True,
            "limiteVariacaoPercentual": 30,
            "faixas": _FAIXAS_FALLBACK,
            "moedas": _MOEDAS_FALLBACK,
        }


class ParametrosCatalogo(_ClienteQuickConfig):
    """BUSCAR — só o catálogo (rótulo da faixa na leitura); degrada sem derrubar o GET."""

    def __init__(
        self,
        cluster_members: Optional[str] = None,
        app_name: Optional[str] = None,
        ttl_s: Optional[int] = None,
        key_faixas: Optional[str] = None,
        key_moedas: Optional[str] = None,
    ):
        super().__init__(cluster_members, app_name, ttl_s)
        self._key_faixas = key_faixas or settings.quickconfig_key_faixas
        self._key_moedas = key_moedas or settings.quickconfig_key_moedas

    def _buscar(self, service: ConfigurationService) -> dict:
        faixas_raw = service.get_config_for_app(self._app_name, self._key_faixas, "[]")
        moedas_raw = service.get_config_for_app(self._app_name, self._key_moedas, "[]")
        return {
            "faixas": self._parse_json(faixas_raw, []),
            "moedas": self._parse_json(moedas_raw, []),
        }

    def _fallback(self) -> dict:
        """Mock das faixas quando o QuickConfig está indisponível."""
        return {"faixas": _FAIXAS_FALLBACK, "moedas": _MOEDAS_FALLBACK}
