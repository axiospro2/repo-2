"""Rotas do BUSCAR (mesma Lambda do salvar):
  - GET /faturamento/{documento}              → read-through (base→endpoint→manual)
  - GET /conglomerados/{documento}/subgrupos  → hierarquia crua do NJ6 (integrantes)

Tela única, sem abas e sem paginação (confirmado com o PO) — o GET de faturamento
sempre devolve a matriz + todos os subgrupos numa lista só.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path

from app.adapters.parametros import ParametrosCatalogo
from app.adapters.repository import DynamoRepository
from app.api.deps import get_catalogo, get_endpoint, get_nj6, get_repo
from app.api.schemas import conglomerado_out, faturamento_out
from app.api.validacao import DOCUMENTO_DESCRICAO, DOCUMENTO_PATTERN
from app.core.logging import bind_context, get_logger, log_event
from app.domain import service_buscar as service
from app.domain.models import Origem

router = APIRouter()
_logger = get_logger("faturamento.api")


@router.get("/faturamento/{documento}")
def buscar(
    documento: str = Path(..., pattern=DOCUMENTO_PATTERN, description=DOCUMENTO_DESCRICAO),
    repo: DynamoRepository = Depends(get_repo),
    nj6=Depends(get_nj6),
    endpoint=Depends(get_endpoint),
    catalogo: ParametrosCatalogo = Depends(get_catalogo),
) -> dict:
    bind_context(conglomerado_doc=documento)
    log_event(_logger, "faturamento.buscar.recebido")

    fat = service.obter_faturamento(documento, repo, nj6, endpoint, catalogo)
    persistido = any(m.origem == Origem.BASE for m in fat.marcadores)
    return faturamento_out(fat, persistido=persistido)


@router.get("/conglomerados/{documento}/subgrupos")
def subgrupos(
    documento: str = Path(..., pattern=DOCUMENTO_PATTERN, description=DOCUMENTO_DESCRICAO),
    nj6=Depends(get_nj6),
) -> dict:
    bind_context(conglomerado_doc=documento)
    log_event(_logger, "faturamento.subgrupos.recebido", level="info")
    try:
        cong = service.listar_subgrupos(documento, nj6)
        log_event(
            _logger,
            "faturamento.subgrupos.resolvido",
            level="info",
            qtd_subgrupos=len(cong.subgrupos),
            nome_grupo=cong.nome_grupo_economico,
        )
        return conglomerado_out(cong)
    except Exception as e:
        _logger.exception(
            "faturamento.subgrupos.erro",
            extra={
                "ctx": {
                    "event": "faturamento.subgrupos.erro",
                    "tipo_erro": type(e).__name__,
                    "mensagem": str(e),
                    "documento": documento,
                }
            },
        )
        raise
