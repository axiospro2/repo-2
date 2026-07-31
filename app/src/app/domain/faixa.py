"""De-para valor → faixa e rótulo da faixa. As faixas vêm do serviço de parâmetros.

Cada faixa: ``{"codigo", "descricao", "min", "max"}`` — ``max`` None = sem teto. Intervalo [min, max).
Na LEITURA usamos a descrição (rótulo que a tela mostra) e, quando há valor específico mas
não faixa gravada, o de-para para exibir a faixa correspondente. No SALVAR, só o de-para.

``valor_em_reais``/``multiplicador_unidade``: os limiares de faixa (``min``/``max``) estão em
reais absolutos (ex.: "R$ 360 mil" = 360000). A tela do CRA oferece 4 unidades no combo
("unitário", "mil", "milhões", "bilhões") numa escala linear normal (base 10, sem exceção pro
default) — confirmado com o dono do negócio olhando a tela real: um valor de "6.500.000,00"
com unidade "mil" aparece na listagem como "R$ 6,5 BI" (6.500.000 × 1.000 = 6.500.000.000),
não como "milhões" sendo tratado à parte. `"unitário"` é quem tem multiplicador ×1 (o valor já
é o número de reais); as outras escalam a partir dele.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

_MULTIPLICADORES_UNIDADE: dict[str, Decimal] = {
    "unitario": Decimal(1),
    "unitário": Decimal(1),
    "mil": Decimal(1_000),
    "milhao": Decimal(1_000_000),
    "milhão": Decimal(1_000_000),
    "milhoes": Decimal(1_000_000),
    "milhões": Decimal(1_000_000),
    "bilhao": Decimal(1_000_000_000),
    "bilhão": Decimal(1_000_000_000),
    "bilhoes": Decimal(1_000_000_000),
    "bilhões": Decimal(1_000_000_000),
}


def multiplicador_unidade(unidade: Optional[str]) -> Optional[Decimal]:
    """Fator para converter um valor bruto na unidade dada para reais absolutos.

    None = unidade desconhecida (o chamador decide: falhar fechado ou logar e seguir).
    """
    chave = (unidade or "milhoes").strip().lower()
    return _MULTIPLICADORES_UNIDADE.get(chave)


def valor_em_reais(valor: Decimal, unidade: Optional[str]) -> Optional[Decimal]:
    """``valor`` bruto × multiplicador da unidade = valor em reais (escala das faixas).

    None = unidade desconhecida (mesma semântica de `multiplicador_unidade`).
    """
    fator = multiplicador_unidade(unidade)
    return None if fator is None else valor * fator


def de_para_valor_para_faixa(valor: Decimal, faixas: list[dict]) -> Optional[str]:
    """Mapeia um valor (já em reais) para o código da faixa (ou None se fora de todas)."""
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
