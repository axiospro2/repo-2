"""Exceções de domínio (mapeadas para HTTP nos exception handlers do FastAPI)."""
from __future__ import annotations


class DominioError(Exception):
    """Erro genérico de domínio → HTTP 400."""


class NaoEncontrado(DominioError):
    """Recurso não encontrado → HTTP 404."""


class ErroValidacao(DominioError):
    """Falha de validação de regra de negócio → HTTP 422."""


class FaixaObrigatoria(ErroValidacao):
    """Marcador sem valor específico e sem faixa → HTTP 422."""


class ConfirmacaoNecessaria(DominioError):
    """Divergência não confirmada → HTTP 409. Carrega a lista de divergências."""

    def __init__(self, divergencias: list[dict]):
        self.divergencias = divergencias
        super().__init__("Divergência(s) detectada(s); reenvie confirmando.")
