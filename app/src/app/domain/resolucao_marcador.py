"""Resolução de 1 marcador de faturamento: banco (BASE) vs Endpoint vs MANUAL.

Extraído de `service_buscar.py` para isolar a lógica de "qual valor vence
para este subgrupo" (quarentena → banco sempre vence → fallback MANUAL) da
orquestração do fluxo BUSCAR como um todo.

Confirmado com o PO: as regras R1/R2/R3 (`domain/eleicao.py`) só se aplicam
à eleição entre as análises cruas do Endpoint — nunca são revalidadas contra
um registro já salvo no nosso banco. Faz sentido: não temos como saber se um
valor digitado pelo analista foi "auditado"/"original" nem qual a categoria
do balanço — esses metadados só existem do lado do Endpoint. Por isso, um
subgrupo com valor salvo no banco **sempre vence**, sem revalidação nem
checagem de idade — e nem precisa consultar o Endpoint para ele
(`domain/service_buscar.py::_alvos_sem_valor_salvo` filtra isso antes de
chamar o Endpoint em paralelo).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

from app.core.logging import get_logger, log_event
from app.domain.faixa import de_para_valor_para_faixa, descricao_da_faixa, valor_em_reais
from app.domain.models import InfoFaturamento, MarcadorFaturamento, Nivel, Origem

_logger = get_logger("faturamento.buscar.resolucao")


def resolver_marcador(
    nivel: Nivel,
    cdoc: str,
    sdoc: str,
    nome: Optional[str],
    salvo: Optional[MarcadorFaturamento],
    resultado_endpoint: object,  # já resolvido pelo fetch paralelo (só p/ quem não tem banco)
    faixas: list[dict],
) -> MarcadorFaturamento:
    """Resolve 1 marcador.

    Ordem de prioridade:
    1. Quarentena: se banco está em quarentena com anterior válido → usa anterior
    2. Banco com valor → usa banco (sempre vence, sem revalidação R1/R2/R3/idade)
    3. Só endpoint (banco vazio) → usa endpoint (já eleito por R1/R2/R3)
    4. Nenhum → MANUAL
    """
    # 1. Quarentena tem prioridade absoluta
    if salvo is not None and salvo.quarentena:
        log_event(_logger, "faturamento.buscar.quarentena", level="debug", subgrupo=sdoc)
        m = aplicar_quarentena(salvo)
        enriquecer_faixa(m, faixas)
        return m

    if salvo is not None and not salvo.atual.vazio:
        log_event(_logger, "faturamento.buscar.banco_vence", level="debug", subgrupo=sdoc)
        m = salvo

    elif resultado_endpoint is not None:
        log_event(_logger, "faturamento.buscar.usa_endpoint", level="debug", subgrupo=sdoc)
        m = marcador_do_endpoint(cdoc, sdoc, nivel, nome, resultado_endpoint, faixas)

    else:
        log_event(_logger, "faturamento.buscar.nenhum_valido_manual", level="debug", subgrupo=sdoc)
        m = MarcadorFaturamento(
            conglomerado_doc=cdoc,
            subgrupo_doc=sdoc,
            nivel=nivel,
            nome=nome,
            origem=Origem.MANUAL,
        )

    enriquecer_faixa(m, faixas)
    return m


def marcador_do_endpoint(
    cdoc: str,
    sdoc: str,
    nivel: Nivel,
    nome: Optional[str],
    res,
    faixas: list[dict],
) -> MarcadorFaturamento:
    """Cria MarcadorFaturamento a partir do resultado do endpoint."""
    valor_reais = valor_em_reais(res.valor_faturamento, res.unidade)
    if valor_reais is None:
        log_event(
            _logger,
            "faturamento.buscar.unidade_desconhecida",
            level="warning",
            subgrupo=sdoc,
            unidade=res.unidade,
        )
    faixa_codigo = (
        de_para_valor_para_faixa(valor_reais, faixas) if valor_reais is not None else None
    )

    m = MarcadorFaturamento(
        conglomerado_doc=cdoc,
        subgrupo_doc=sdoc,
        nivel=nivel,
        nome=nome,
        atual=InfoFaturamento(
            valor=res.valor_faturamento,
            faixa_codigo=faixa_codigo,
            data_ref_balanco=res.data_ref_balanco,
            moeda=res.moeda or "BRL",
            unidade=res.unidade or "milhoes",
            id_spread=res.id_spread,
            sistema_origem=res.sistema_origem,
        ),
        origem=Origem.ENDPOINT,
        aceite=False,
    )
    m.faturamento_cra = replace(m.atual)
    return m


def aplicar_quarentena(m: MarcadorFaturamento) -> MarcadorFaturamento:
    """Se em quarentena e há `anterior` não-vazio, elege o `anterior` como valor vigente."""
    if m.quarentena and m.anterior is not None and not m.anterior.vazio:
        return replace(m, atual=m.anterior, em_quarentena=True)
    return m


def enriquecer_faixa(m: MarcadorFaturamento, faixas: list[dict]) -> None:
    """Preenche o rótulo (descrição) da faixa vigente para a tela exibir."""
    for info in (m.atual, m.anterior, m.faturamento_cra):
        if info is not None:
            info.faixa_descricao = descricao_da_faixa(info.faixa_codigo, faixas)
