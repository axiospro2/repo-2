"""Rota do BUSCAR (mesma Lambda do salvar):
  - GET /faturamento/{documento}      → read-through (base→endpoint→manual), documento exato
  - GET /grupos-economicos?documento= → busca "like" no NJ6 (autocomplete), documento parcial

Tela única, sem abas e sem paginação (confirmado com o PO) — o GET de faturamento sempre
devolve a matriz + todos os subgrupos numa lista só, já resolvendo a hierarquia no NJ6 por
dentro (`service.obter_faturamento`). Ele exige o documento EXATO (raiz do conglomerado).

`GET /grupos-economicos` é o passo anterior: o front digita um documento parcial (o NJ6
casa "como um LIKE"), essa rota devolve só a lista de grupos econômicos que batem
(cabeça + subgrupos, sem faturamento nenhum) pra o analista escolher — depois disso o
front chama `GET /faturamento/{documento}` com o documento exato escolhido.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query

from app.adapters.parametros import ParametrosCatalogo
from app.adapters.repository import DynamoRepository
from app.api.deps import get_catalogo, get_endpoint, get_nj6, get_repo
from app.api.schemas import faturamento_out, grupos_out
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


@router.get("/grupos-economicos")
def buscar_grupos(
    documento: str = Query(..., pattern=DOCUMENTO_PATTERN, description=DOCUMENTO_DESCRICAO),
    nj6=Depends(get_nj6),
) -> dict:
    bind_context(conglomerado_doc=documento)
    log_event(_logger, "faturamento.buscar_grupos.recebido")

    grupos = service.buscar_grupos_economicos(documento, nj6)
    return grupos_out(grupos)
