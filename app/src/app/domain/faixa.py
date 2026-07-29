"""De-para valor → faixa e rótulo da faixa. As faixas vêm do serviço de parâmetros.

Cada faixa: ``{"codigo", "descricao", "min", "max"}`` — ``max`` None = sem teto. Intervalo [min, max).
Na LEITURA usamos a descrição (rótulo que a tela mostra) e, quando há valor específico mas
não faixa gravada, o de-para para exibir a faixa correspondente. No SALVAR, só o de-para.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional


def de_para_valor_para_faixa(valor: Decimal, faixas: list[dict]) -> Optional[str]:
    """Mapeia um valor específico para o código da faixa (ou None se fora de todas)."""
    return next((f["codigo"] for f in faixas if _pertence(valor, f)), None)


def descricao_da_faixa(codigo: Optional[str], faixas: list[dict]) -> Optional[str]:
    """Rótulo humano da faixa (ex.: 'R$ 360 mil a R$ 4,8 MM'). None se não achar."""
    if not codigo:
        return None
    return next((f.get("descricao") for f in faixas if f.get("codigo") == codigo), None)


def _pertence(valor: Decimal, faixa: dict) -> bool:
    minimo = Decimal(str(faixa["min"]))
    maximo = faixa.get("max")
    if maximo is None:  # faixa sem teto
        return valor >= minimo
    return minimo <= valor < Decimal(str(maximo))
