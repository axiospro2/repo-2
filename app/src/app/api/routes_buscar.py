"""Rotas do BUSCAR (mesma Lambda do salvar):
  - GET /faturamento/{documento}?aba=&limit=&cursor=    → read-through (base→endpoint→manual)
  - GET /conglomerados/{documento}/subgrupos            → hierarquia crua do NJ6 (integrantes)
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Path, Query

from app.adapters.parametros import ParametrosCatalogo
from app.adapters.repository import DynamoRepository
from app.api.deps import get_catalogo, get_endpoint, get_nj6, get_repo
from app.api.schemas import conglomerado_out, faturamento_out
from app.core.logging import bind_context, get_logger, log_event
from app.domain import service_buscar as service
from app.domain.models import Origem

router = APIRouter()
_logger = get_logger("faturamento.api")


@router.get("/faturamento/{documento}")
def buscar(
    documento: str = Path(..., description="CPF/CNPJ/CGI do conglomerado"),
    aba: Optional[str] = Query(None, description="CONGLOMERADO (default) | SUBGRUPO"),
    limit: int = Query(service.LIMIT_PADRAO, ge=1, le=service.LIMIT_MAXIMO,
                        description="Itens por página (aba CONGLOMERADO)"),
    cursor: Optional[str] = Query(None, description="Cursor de paginação (proximoCursor da resposta)"),
    repo: DynamoRepository = Depends(get_repo),
    nj6=Depends(get_nj6),
    endpoint=Depends(get_endpoint),
    catalogo: ParametrosCatalogo = Depends(get_catalogo),
) -> dict:
    bind_context(conglomerado_doc=documento, aba=aba or "CONGLOMERADO")
    log_event(_logger, "faturamento.buscar.recebido", limit=limit, tem_cursor=bool(cursor))

    fat = service.obter_faturamento(
        documento, aba, repo, nj6, endpoint, catalogo, limit=limit, cursor=cursor
    )
    persistido = any(m.origem == Origem.BASE for m in fat.marcadores)
    return faturamento_out(fat, persistido=persistido)


@router.get("/conglomerados/{documento}/subgrupos")
def subgrupos(
    documento: str = Path(..., description="CPF/CNPJ/CGI do conglomerado"),
    nj6=Depends(get_nj6),
) -> dict:
    bind_context(conglomerado_doc=documento)
    log_event(_logger, "faturamento.subgrupos.recebido", level="info")
    try:
        cong = service.listar_subgrupos(documento, nj6)
        log_event(_logger, "faturamento.subgrupos.resolvido", level="info",
                  qtd_subgrupos=len(cong.subgrupos), nome_grupo=cong.nome_grupo_economico)
        result = conglomerado_out(cong)
        log_event(_logger, "faturamento.subgrupos.serializado", level="debug")
        return result
    except Exception as e:
        _logger.exception("faturamento.subgrupos.erro",
                           extra={"ctx": {
                               "event": "faturamento.subgrupos.erro",
                               "tipo_erro": type(e).__name__,
                               "mensagem": str(e),
                               "documento": documento
                           }})
        raise
