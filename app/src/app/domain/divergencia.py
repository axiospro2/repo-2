"""Gate de divergência — compara o valor NOVO com o já salvo.

Roda no `salvar` ANTES de gravar. Divergência não confirmada → HTTP 409.
Compara: variação de valor (% acima do limite), troca de moeda e troca de unidade.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from app.domain.models import MarcadorFaturamento


def _diferente(x: Optional[str], y: Optional[str]) -> bool:
    return x is not None and y is not None and x.upper() != y.upper()


def avaliar(novo: MarcadorFaturamento, existente: Optional[MarcadorFaturamento],
            limite_pct: int) -> list[dict]:
    """Lista as divergências entre o marcador novo e o existente (vazio = sem divergência)."""
    out: list[dict] = []
    if existente is None or existente.atual is None:
        return out

    a, b = novo.atual, existente.atual

    if a.valor is not None and b.valor is not None and b.valor != 0:
        variacao = (abs(a.valor - b.valor) / abs(b.valor) * Decimal(100)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if variacao > Decimal(limite_pct):
            out.append({
                "tipo": "VALOR",
                "subgrupoDoc": novo.subgrupo_doc,
                "de": format(b.valor, "f"),
                "para": format(a.valor, "f"),
                "variacaoPercentual": format(variacao, "f"),
            })

    if _diferente(a.moeda, b.moeda):
        out.append({"tipo": "MOEDA", "subgrupoDoc": novo.subgrupo_doc, "de": b.moeda, "para": a.moeda})

    if _diferente(a.unidade, b.unidade):
        out.append({"tipo": "UNIDADE", "subgrupoDoc": novo.subgrupo_doc, "de": b.unidade, "para": a.unidade})

    return out
