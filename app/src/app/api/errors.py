"""Exception handlers: domínio → HTTP. Registrados no app FastAPI.

Mapa: ConfirmacaoNecessaria→409 · NaoEncontrado→404 · ErroValidacao (e subclasses, ex.
FaixaObrigatoria)→422 · DominioError→400. O FastAPI resolve o handler pela MRO da exceção,
então subclasses de ErroValidacao caem no handler dela com o `tipo` correto (type(e).__name__).
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger
from app.domain.errors import ConfirmacaoNecessaria, DominioError, ErroValidacao, NaoEncontrado

_logger = get_logger("faturamento.erro")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ConfirmacaoNecessaria)
    async def _confirmacao(_: Request, e: ConfirmacaoNecessaria):
        return JSONResponse(
            status_code=409,
            content={
                "tipo": "ConfirmacaoNecessaria",
                "erro": str(e),
                "divergencias": e.divergencias,
            },
        )

    @app.exception_handler(NaoEncontrado)
    async def _nao_encontrado(_: Request, e: NaoEncontrado):
        return JSONResponse(status_code=404, content={"erro": str(e)})

    @app.exception_handler(ErroValidacao)
    async def _validacao(_: Request, e: ErroValidacao):
        return JSONResponse(status_code=422, content={"erro": str(e), "tipo": type(e).__name__})

    @app.exception_handler(DominioError)
    async def _dominio(_: Request, e: DominioError):
        # 400 genérico — mas loga, porque DominioError "puro" não deveria vazar sem tratamento.
        _logger.exception(
            "faturamento.erro_dominio", extra={"ctx": {"event": "faturamento.erro_dominio"}}
        )
        return JSONResponse(status_code=400, content={"erro": str(e)})

    @app.exception_handler(Exception)
    async def _unhandled_exception(request: Request, e: Exception):
        """Captura exceções não mapeadas (500)."""
        _logger.exception(
            "faturamento.erro_nao_tratado",
            extra={
                "ctx": {
                    "event": "faturamento.erro_nao_tratado",
                    "path": str(request.url.path),
                    "method": request.method,
                    "tipo_erro": type(e).__name__,
                    "mensagem": str(e),
                }
            },
        )
        return JSONResponse(
            status_code=500, content={"erro": "Internal Server Error", "tipo": type(e).__name__}
        )
