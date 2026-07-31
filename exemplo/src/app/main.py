from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from app.api.routes import router
from app.core.logging import (
    bind_context,
    clear_context,
    get_logger,
    log_event,
    setup_logging,
)
from app.core.settings import settings

# Constantes de configuração
PREFIXO_API = "/api-irb-cra-faturamento-bff/v1"
METODOS_CORS = ["GET", "POST", "OPTIONS"]
CABECALHOS_CORS = ["Authorization", "Content-Type"]

log = get_logger("faturamento-bff")


def criar_app() -> FastAPI:
    """Cria e configura a instância da aplicação FastAPI."""
    setup_logging()

    app = FastAPI(
        title="Faturamento IRB — BFF",
        version="1.0.0",
        description=(
            "BFF para a Lambda de Faturamento do IRB, "
            "repassando requisições para a API interna."
        ),
    )

    _configurar_rotas(app)
    _configurar_middlewares(app)

    return app


def _configurar_rotas(app: FastAPI) -> None:
    """Registra as rotas da aplicação."""
    app.include_router(router, prefix=PREFIXO_API)

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok"}


def _configurar_middlewares(app: FastAPI) -> None:
    """Configura os middlewares da aplicação."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.cors_allow_origin],
        allow_methods=METODOS_CORS,
        allow_headers=CABECALHOS_CORS,
    )

    @app.middleware("http")
    async def vincular_contexto_invocacao(request: Request, call_next):
        # Limpa estado de invocacoes anteriores (Lambda reaproveita o processo)
        clear_context()

        contexto_aws = request.scope.get("aws.context")
        request_id = getattr(contexto_aws, "aws_request_id", None) or str(uuid.uuid4())

        bind_context(
            request_id=request_id,
            http_method=request.method,
            http_path=request.url.path,
        )

        inicio = time.perf_counter()
        try:
            log_event(log, "http.request.start")
            response = await call_next(request)
            duracao_ms = round((time.perf_counter() - inicio) * 1000, 2)
            log_event(
                log,
                "http.request.end",
                status_code=response.status_code,
                duration_ms=duracao_ms,
            )
            response.headers["x-request-id"] = request_id
            return response
        except Exception:
            duracao_ms = round((time.perf_counter() - inicio) * 1000, 2)
            log.exception(
                "http.request.error",
                extra={"ctx": {"event": "http.request.error", "duration_ms": duracao_ms}},
            )
            raise
        finally:
            # Garante que nada vaze entre invocacoes reaproveitadas
            clear_context()


app = criar_app()
handler = Mangum(app, lifespan="off")
