"""Regra de negócio do BUSCAR (read-through). Depende dos portos NJ6, Endpoint e Repositório.

Módulo irmão de `service.py` (SALVAR) – mesma Lambda, dois caminhos. Fica separado para não
misturar os protocolos de repositório (leitura x escrita) nem as dependências (o salvar NÃO
usa NJ6/Endpoint).

Fluxo (GET /faturamento/{documento}):

1. NJ6 resolve o conglomerado (e subgrupos) a partir do documento (CPF/CNPJ/CGF).
2. `paginacao.alvos_do_conglomerado` lista a matriz + todos os subgrupos — sem abas, sem
   paginação (confirmado com o PO; a tela é única).
3. Busca o Endpoint em PARALELO, mas SÓ para os alvos que não têm valor salvo no banco —
   um subgrupo com valor no banco vence sempre, sem revalidar nada (`R-RES-001`/`R-PEND-011`
   resolvido), então nem vale a pena consultar o Endpoint para ele.
4. Para cada alvo, `resolucao_marcador.resolver_marcador` decide banco vs Endpoint vs MANUAL.

Este módulo é só o ORQUESTRADOR do fluxo: a lógica de seleção de alvos vive em
`domain/paginacao.py` e a lógica de "qual valor vence por subgrupo" vive em
`domain/resolucao_marcador.py`.

Emite eventos de NEGÓCIO/TÉCNICO pro Datadog. NÃO grava nada (é só leitura).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Protocol

from app.core.logging import get_logger, log_event
from app.domain.models import Conglomerado, Faturamento, MarcadorFaturamento, Origem
from app.domain.paginacao import alvos_do_conglomerado
from app.domain.resolucao_marcador import resolver_marcador

__all__ = [
    "Repositorio",
    "NJ6",
    "Endpoint",
    "Catalogo",
    "obter_faturamento",
    "listar_subgrupos",
]

_logger = get_logger("faturamento.buscar")

_MAX_WORKERS = 10  # limite de threads paralelas ao endpoint


class Repositorio(Protocol):
    def get_conglomerado(self, conglomerado_doc: str) -> list[MarcadorFaturamento]: ...


class NJ6(Protocol):
    def get_por_documento(self, documento: str) -> Conglomerado: ...


class Endpoint(Protocol):
    def buscar(self, documento_raiz: str, asof: Optional[str] = None): ...


class Catalogo(Protocol):
    def obter(self) -> dict: ...


def obter_faturamento(
    documento: str,
    repo: Repositorio,
    nj6: NJ6,
    endpoint: Endpoint,
    catalogo: Catalogo,
) -> Faturamento:
    """Read-through por documento: matriz + subgrupos, banco sempre vence quando presente."""
    cong = nj6.get_por_documento(documento)
    cdoc = cong.cabeca_documento_raiz
    salvos_por_sub = {m.subgrupo_doc: m for m in repo.get_conglomerado(cdoc)}
    faixas = (catalogo.obter() or {}).get("faixas") or []

    alvos = alvos_do_conglomerado(cong)

    # Só consulta o Endpoint pra quem NÃO tem valor salvo no banco — banco sempre vence,
    # então chamar o Endpoint pra esses seria trabalho (e latência) sem efeito no resultado.
    docs_sem_banco = [
        doc for (_, doc, _) in alvos if _precisa_consultar_endpoint(salvos_por_sub.get(doc))
    ]
    resultados_endpoint = _buscar_endpoint_paralelo(docs_sem_banco, endpoint)

    marcadores = [
        resolver_marcador(
            nivel,
            cdoc,
            doc,
            nome,
            salvos_por_sub.get(doc),
            resultados_endpoint.get(doc),
            faixas,
        )
        for (nivel, doc, nome) in alvos
    ]

    _log_resolucao(cdoc, marcadores)
    return Faturamento(
        conglomerado_doc=cdoc,
        nome_grupo_economico=cong.nome_grupo_economico,
        segmento=cong.segmento,
        marcadores=marcadores,
    )


def listar_subgrupos(documento: str, nj6: NJ6) -> Conglomerado:
    """GET /conglomerados/{documento}/subgrupos — hierarquia crua do NJ6 (tabela de integrantes)."""
    try:
        log_event(_logger, "service.listar_subgrupos.inicio", level="debug", documento=documento)
        cong = nj6.get_por_documento(documento)
        log_event(
            _logger,
            "service.listar_subgrupos.sucesso",
            level="debug",
            documento=documento,
            gtd_subgrupos=len(cong.subgrupos),
            nome_grupo=cong.nome_grupo_economico,
        )
        return cong
    except Exception as e:
        _logger.exception(
            "service.listar_subgrupos.erro",
            extra={
                "ctx": {
                    "event": "service.listar_subgrupos.erro",
                    "documento": documento,
                    "tipo_erro": type(e).__name__,
                    "mensagem": str(e),
                }
            },
        )
        raise


# —————— chamadas paralelas ao endpoint ——————


def _precisa_consultar_endpoint(salvo: Optional[MarcadorFaturamento]) -> bool:
    """Banco sempre vence quando tem valor ou está em quarentena — só falta chamar o
    Endpoint pra quem não tem NADA salvo (banco ausente ou vazio, sem quarentena)."""
    if salvo is None:
        return True
    if salvo.quarentena:
        return False  # quarentena usa o `anterior`, nunca o Endpoint
    return salvo.atual.vazio


def _buscar_endpoint_paralelo(docs: list[str], endpoint: Endpoint) -> dict[str, object]:
    """Busca o endpoint para vários subgrupos em PARALELO.

    Retorna dict { subgrupo_doc → ResultadoFaturamento | None }.
    Erros em 1 subgrupo NÃO derrubam os outros — tratado individualmente.
    """
    resultados: dict[str, object] = {}
    if not docs:
        return resultados

    workers = min(_MAX_WORKERS, len(docs))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futuro_para_doc = {executor.submit(endpoint.buscar, doc): doc for doc in docs}
        for futuro in as_completed(futuro_para_doc):
            doc = futuro_para_doc[futuro]
            try:
                resultados[doc] = futuro.result()
            except Exception as exc:
                log_event(
                    _logger,
                    "faturamento.buscar.endpoint_erro_paralelo",
                    level="warning",
                    subgrupo=doc,
                    erro=str(exc),
                )
                resultados[doc] = None

    return resultados


# ----------- agregado -----------


def _log_resolucao(cdoc: str, marcadores: list[MarcadorFaturamento]) -> None:
    por_origem = {origem: sum(1 for m in marcadores if m.origem == origem) for origem in Origem}
    log_event(
        _logger,
        "faturamento.buscar.resolvido",
        conglomerado_doc=cdoc,
        qtd_marcadores=len(marcadores),
        origem_dados="BASE" if por_origem[Origem.BASE] else "PREVIEW",
        base=por_origem[Origem.BASE],
        endpoint=por_origem[Origem.ENDPOINT],
        manual=por_origem[Origem.MANUAL],
    )
