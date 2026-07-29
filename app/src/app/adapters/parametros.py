"""Clientes do serviço de parâmetros (HTTP + cache TTL + credenciais M2M).

Dois consumidores, mesma infraestrutura (``_ClienteParametros``):
  - ``ParametrosClient`` (SALVAR): snapshot autoritativo — limite% de divergência, gate,
    faixas e moedas.
  - ``ParametrosCatalogo`` (BUSCAR): só o catálogo (faixas → rótulo, moedas).

Ambos: cache em memória por TTL (Lambda quente), retry com tenacity nas falhas transitórias e
log técnico (`parametros.fetch`) com cache_hit/latência. Em indisponibilidade cada cliente define
o SEU fallback — e o fallback NUNCA é cacheado (tenta de novo na próxima invocação):
  - salvar: gate DESLIGA (não bloqueia injustamente) e faixas/moedas vazias — o service então
    falha FECHADO (422), pois sem catálogo não dá pra validar com segurança.
  - buscar: catálogo vazio — a leitura segue funcionando, só não enriquece o rótulo da faixa.
    Nunca derruba o GET por causa disso.
"""

from __future__ import annotations

import json
import time
import urllib.request

from app.adapters.auth import TokenProvider, build_token_provider
from app.core.logging import get_logger, log_event
from app.core.retry import http_retry
from app.core.settings import settings

_logger = get_logger("faturamento.parametros")


class _ClienteParametros:
    """Template do GET /parametros: cache TTL + retry. Subclasses definem mapeamento e fallback."""

    def __init__(self, base_url: str | None = None, ttl_s: int | None = None,
                 token: TokenProvider | None = None):
        self._base = (base_url or settings.parametros_base_url).rstrip("/")
        self._ttl = ttl_s if ttl_s is not None else settings.parametros_ttl_s
        self._token = token or build_token_provider()
        self._cache: dict | None = None
        self._expira_em: float = 0.0

    def obter(self) -> dict:
        """Snapshot de parâmetros (cacheado). Nunca lança — cai no fallback da subclasse."""
        agora = time.time()
        if self._cache is not None and agora < self._expira_em:
            log_event(_logger, "parametros.fetch", level="debug", cache_hit=True)
            return self._cache

        inicio = time.perf_counter()
        try:
            snapshot = self._mapear(self._buscar())
        except Exception as e:
            log_event(_logger, "parametros.indisponivel", level="error", erro=str(e))
            return self._fallback()

        self._cache = snapshot
        self._expira_em = agora + self._ttl
        log_event(_logger, "parametros.fetch", level="debug", cache_hit=False,
                  latency_ms=round((time.perf_counter() - inicio) * 1000, 1),
                  faixas=len(snapshot.get("faixas") or []),
                  moedas=len(snapshot.get("moedas") or []))
        return snapshot

    # ───────── pontos de extensão ─────────

    def _mapear(self, data: dict) -> dict:
        """Payload cru do serviço → snapshot que este cliente expõe."""
        raise NotImplementedError

    def _fallback(self) -> dict:
        """Snapshot degradado quando o serviço está indisponível (não é cacheado)."""
        raise NotImplementedError

    # ───────── HTTP ─────────

    @http_retry
    def _buscar(self) -> dict:
        req = urllib.request.Request(f"{self._base}/parametros", headers=self._token.auth_headers())
        with urllib.request.urlopen(req, timeout=settings.parametros_timeout_s) as r:
            return json.loads(r.read().decode("utf-8"))


class ParametrosClient(_ClienteParametros):
    """SALVAR — snapshot completo (gate de divergência + catálogo autoritativo)."""

    def _mapear(self, data: dict) -> dict:
        return {
            "limiteVariacaoPercentual": int(data.get("limiteVariacaoPercentual", 0)),
            "gateDivergenciaAtivo": bool(data.get("gateDivergenciaAtivo", False)),
            "faixas": data.get("faixas") or [],
            "moedas": data.get("moedas") or [],
        }
    def _mapear(self, data: dict) -> dict:
        """Payload cru do serviço → snapshot que este cliente expõe."""
        raise NotImplementedError

    def _fallback(self) -> dict:
        """Snapshot degradado quando o serviço está indisponível (não é cacheado)."""
        raise NotImplementedError

    # ─────────── HTTP ───────────

    @http_retry
    def _buscar(self) -> dict:
        req = urllib.request.Request(f"{self._base}/parametros", headers=self._token.auth_headers())
        with urllib.request.urlopen(req, timeout=settings.parametros_timeout_s) as r:
            return json.loads(r.read().decode("utf-8"))


class ParametrosClient(_ClienteParametros):
    """SALVAR — snapshot completo (gate de divergência + catálogo autoritativo)."""

    def _mapear(self, data: dict) -> dict:
        return {
            "limiteVariacaoPercentual": int(data.get("limiteVariacaoPercentual", 0)),
            "gateDivergenciaAtivo": bool(data.get("gateDivergenciaAtivo", False)),
            "faixas": data.get("faixas") or [],
            "moedas": data.get("moedas") or [],
        }

    def _fallback(self) -> dict:
        """Mock das faixas quando o serviço está indisponível."""
        return {
            "limiteVariacaoPercentual": 30,
            "gateDivergenciaAtivo": False,
            "faixas": [
                {"codigo": "FAIXA_1", "descricao": "R$ 360 mil a R$ 4,8 MM", "min": 360000, "max": 4800000},
                {"codigo": "FAIXA_2", "descricao": "R$ 4,8 MM a R$ 20 MM", "min": 4800000, "max": 20000000},
                {"codigo": "FAIXA_3", "descricao": "R$ 20 MM a R$ 100 MM", "min": 20000000, "max": 100000000},
                {"codigo": "FAIXA_4", "descricao": "R$ 100 MM a R$ 500 MM", "min": 100000000, "max": 500000000},
                {"codigo": "FAIXA_5", "descricao": "R$ 500 MM a R$ 2 BI", "min": 500000000, "max": 2000000000},
                {"codigo": "FAIXA_6", "descricao": "Acima de R$ 2 BI", "min": 2000000000, "max": None},
            ],
            "moedas": ["BRL", "USD"],
        }


class ParametrosCatalogo(_ClienteParametros):
    """BUSCAR — só o catálogo (rótulo da faixa na leitura); degrada sem derrubar o GET."""

    def _mapear(self, data: dict) -> dict:
        return {"faixas": data.get("faixas") or [], "moedas": data.get("moedas") or []}

    def _fallback(self) -> dict:
        """Mock das faixas quando o serviço está indisponível."""
        return {
            "faixas": [
                {"codigo": "FAIXA_1", "descricao": "R$ 360 mil a R$ 4,8 MM", "min": 360000, "max": 4800000},
                {"codigo": "FAIXA_2", "descricao": "R$ 4,8 MM a R$ 20 MM", "min": 4800000, "max": 20000000},
                {"codigo": "FAIXA_3", "descricao": "R$ 20 MM a R$ 100 MM", "min": 20000000, "max": 100000000},
                {"codigo": "FAIXA_4", "descricao": "R$ 100 MM a R$ 500 MM", "min": 100000000, "max": 500000000},
                {"codigo": "FAIXA_5", "descricao": "R$ 500 MM a R$ 2 BI", "min": 500000000, "max": 2000000000},
                {"codigo": "FAIXA_6", "descricao": "Acima de R$ 2 BI", "min": 2000000000, "max": None},
            ],
            "moedas": ["BRL", "USD"],
        }
