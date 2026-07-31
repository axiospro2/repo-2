"""Rota do SALVAR — POST /faturamento/{documento}."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, Path

from app.adapters.parametros import ParametrosClient
from app.adapters.repository import DynamoRepository
from app.api.deps import get_parametros, get_repo
from app.api.schemas import FaturamentoRequest, faturamento_out
from app.api.validacao import DOCUMENTO_DESCRICAO, DOCUMENTO_PATTERN
from app.core.logging import bind_context, get_logger, log_event
from app.core.settings import settings
from app.domain import service

router = APIRouter()
_logger = get_logger("faturamento.api")


@router.post("/faturamento/{documento}", status_code=201)
def salvar(
    body: FaturamentoRequest,
    documento: str = Path(..., pattern=DOCUMENTO_PATTERN, description=DOCUMENTO_DESCRICAO),
    racf: Optional[str] = Header(
        None, alias=settings.racf_header, description="RACF de quem informou (responsabilização)"
    ),
    repo: DynamoRepository = Depends(get_repo),
    parametros: ParametrosClient = Depends(get_parametros),
) -> dict:
    bind_context(conglomerado_doc=body.conglomerado_doc or documento, racf=racf)
    log_event(_logger, "faturamento.salvar.recebido", qtd_marcadores=len(body.marcadores))

    fat = body.to_domain(documento, racf=racf)
    salvo = service.salvar(fat, repo, parametros.obter())
    return faturamento_out(salvo, persistido=True)
