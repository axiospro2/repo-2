"""Seleção de "alvos" (cabeça do conglomerado + subgrupos) para o fluxo BUSCAR.

Confirmado com o PO: a tela é única — sem abas (Conglomerado/Subgrupo) e sem
paginação. `alvos_do_conglomerado` sempre devolve a matriz (cabeça do
conglomerado) + todos os subgrupos, juntos, numa lista só.
"""

from __future__ import annotations

from typing import Optional

from app.domain.models import Conglomerado, Nivel

# (nivel, documento, nome) — um "alvo" a resolver no fluxo BUSCAR.
Alvo = tuple[Nivel, str, Optional[str]]


def alvos_do_conglomerado(cong: Conglomerado) -> list[Alvo]:
    """Matriz (cabeça do conglomerado) + todos os subgrupos, sem duplicar o
    documento da matriz caso ele também apareça na lista crua de subgrupos do NJ6."""
    matriz: Alvo = (Nivel.CONGLOMERADO, cong.cabeca_documento_raiz, cong.nome_grupo_economico)
    subgrupos = [alvo for alvo in subgrupos_unicos(cong) if alvo[1] != cong.cabeca_documento_raiz]
    return [matriz, *subgrupos]


def subgrupos_unicos(cong: Conglomerado) -> list[Alvo]:
    alvos: list[Alvo] = []
    vistos: set[str] = set()
    for sub in cong.subgrupos:
        doc = sub.cabeca_documento_raiz
        if doc not in vistos:
            vistos.add(doc)
            alvos.append((Nivel.SUBGRUPO, doc, sub.nome_subgrupo))
    return alvos
