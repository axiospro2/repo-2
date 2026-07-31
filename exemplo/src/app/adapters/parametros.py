"""Catálogo (faixas + moedas) do serviço de parâmetros, pro front popular dropdowns.

O BFF busca configurações do QuickConfig. Cache por TTL; em caso de erro na
busca, cai de volta para o cache expirado (se houver) como fallback.
"""
from __future__ import annotations

import json
import time
from typing import Any

from manager import ConfigurationService, QuickConfigConfigurationSource

from ..core.logging import get_logger, log_event
from ..core.settings import settings

logger = get_logger("bff.parametros")


class ParametrosCatalogo:
    def __init__(
        self,
        cluster_members: str | None = None,
        app_name: str | None = None,
        ttl_s: int | None = None,
        key_faixas: str | None = None,
        key_moedas: str | None = None,
    ):
        """Inicializa cliente do QuickConfig para buscar catálogo.

        Args:
            cluster_members: URLs do QuickConfig separadas por vírgula (ex: "host1:5701,host2:5701")
            app_name: Nome da aplicação no QuickConfig
            ttl_s: Tempo de cache em segundos
            key_faixas: Chave de configuração para faixas
            key_moedas: Chave de configuração para moedas
        """
        self._cluster_members = (cluster_members or settings.quickconfig_cluster_members).strip()
        self._app_name = app_name or settings.quickconfig_app_name
        self._ttl = ttl_s if ttl_s is not None else settings.quickconfig_ttl_s
        self._key_faixas = key_faixas or settings.quickconfig_key_faixas
        self._key_moedas = key_moedas or settings.quickconfig_key_moedas

        self._cache: dict | None = None
        self._exp: float = 0.0
        self._config_service: ConfigurationService | None = None

    def _inicializar_servico(self) -> ConfigurationService:
        """Inicializa e retorna o ConfigurationService do QuickConfig."""
        if self._config_service is not None:
            return self._config_service

        if not self._cluster_members:
            raise ValueError("QUICKCONFIG_CLUSTER_MEMBERS não está configurado!")

        try:
            log_event(logger, "quickconfig_connecting", cluster_members=self._cluster_members)
            config_source = QuickConfigConfigurationSource(
                app_name=self._app_name,
                sync=True,
                listener_mode=False,
                cluster_members=self._cluster_members.split(","),
            )
            self._config_service = ConfigurationService(config_source)
            log_event(logger, "quickconfig_connected", level="info")
            return self._config_service
        except Exception:
            logger.exception("quickconfig_connect_failed", extra={"ctx": {"event": "quickconfig_connect_failed"}})
            raise

    def catalogo(self) -> dict:
        """Devolve {"faixas": [...], "moedas": [...]} do QuickConfig (cacheado).

        Returns:
            Dict com chaves 'faixas' e 'moedas' contendo listas de configurações.
        """
        agora = time.time()
        if self._cache is not None and agora < self._exp:
            log_event(logger, "catalogo_cache_hit", level="debug")
            return self._cache

        log_event(logger, "catalogo_fetching", level="debug")
        try:
            service = self._inicializar_servico()

            faixas_raw = service.get_config_for_app(self._app_name, self._key_faixas, "[]")
            faixas = self._parse_json(faixas_raw, [])

            moedas_raw = service.get_config_for_app(self._app_name, self._key_moedas, "[]")
            moedas = self._parse_json(moedas_raw, [])

            self._cache = {"faixas": faixas, "moedas": moedas}
            self._exp = agora + self._ttl

            log_event(
                logger, "catalogo_updated", level="info",
                faixas_count=len(faixas), moedas_count=len(moedas),
            )
            return self._cache

        except Exception:
            logger.exception("catalogo_fetch_failed", extra={"ctx": {"event": "catalogo_fetch_failed"}})
            # Se houver cache expirado, retornar mesmo assim (fallback)
            if self._cache is not None:
                log_event(logger, "catalogo_fallback_stale_cache", level="warning")
                return self._cache
            # Caso contrário, relançar a exceção
            raise

    @staticmethod
    def _parse_json(data: Any, default: Any = None) -> Any:
        """Parse seguro de JSON.

        Args:
            data: Dados a fazer parse (pode ser string JSON ou objeto)
            default: Valor padrão se falhar o parse

        Returns:
            Dado parseado ou default
        """
        try:
            if isinstance(data, str):
                return json.loads(data)
            return data if data is not None else default
        except (json.JSONDecodeError, TypeError) as e:
            # TypeError e defensivo: nao ha caminho conhecido que o dispare hoje
            # (json.loads so e chamado apos confirmar isinstance(data, str)), mas
            # mantido caso o guard acima mude no futuro.
            log_event(logger, "catalogo_parse_json_failed", level="warning", erro=str(e))
            return default
