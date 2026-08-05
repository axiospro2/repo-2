"""Entrypoint da Lambda de Faturamento - FastAPI + Mangum.

Uma Lambda, dois caminhos: SALVAR (POST) e BUSCAR (GET). Handler: ``app.main.handler``
(Mangum adapta o evento API Gateway proxy -> ASGI).
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request
from mangum import Mangum

from app.api.errors import register_exception_handlers
from app.api.routes import router
from app.api.routes_buscar import router as router_buscar
from app.core.logging import bind_context, clear_context, get_logger, log_event, setup_logging

setup_logging()

app = FastAPI(
    title="Faturamento",
    version="1.0.0",
    description="Faturamento IRB - caminhos de salvar (POST) e buscar (GET).",
)
register_exception_handlers(app)

_logger = get_logger("faturamento.main")


@app.middleware("http")
async def _contexto_invocacao(request: Request, call_next):
    """Vincula request_id (Correlação no Datadog) e dados básicos da requisição."""
    clear_context()
    ctx = request.scope.get("aws.context")
    request_id = getattr(ctx, "aws_request_id", None)
    bind_context(
        request_id=request_id,
        http_method=request.method,
        http_path=request.url.path,
    )

    start_time = time.time()
    log_event(
        _logger,
        "faturamento.requisicao.inicio",
        level="info",
        metodo=request.method,
        caminho=request.url.path,
        request_id=request_id,
    )

    try:
        response = await call_next(request)
        latencia_ms = (time.time() - start_time) * 1000
        log_event(
            _logger,
            "faturamento.requisicao.fim",
            level="info",
            metodo=request.method,
            caminho=request.url.path,
            status_code=response.status_code,
            latencia_ms=round(latencia_ms, 2),
        )
        return response
    except Exception as e:
        latencia_ms = (time.time() - start_time) * 1000
        _logger.exception(
            "faturamento.requisicao.erro_middleware",
            extra={
                "ctx": {
                    "event": "faturamento.requisicao.erro_middleware",
                    "metodo": request.method,
                    "caminho": request.url.path,
                    "tipo_erro": type(e).__name__,
                    "latencia_ms": round(latencia_ms, 2),
                }
            },
        )
        raise


@app.get("/health", include_in_schema=False)
def health() -> dict:
    return {"status": "ok"}


app.include_router(
    router, prefix="/irb-cra-faturamento/v1"
)  # SALVAR (POST /faturamento/{documento})
app.include_router(
    router_buscar, prefix="/irb-cra-faturamento/v1"
)  # BUSCAR (GET /faturamento/{documento})

# Entrypoint da AWS Lambda.
handler = Mangum(app)
