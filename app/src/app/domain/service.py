"""Regra de negócio do SALVAR. Depende só do repositório e de um snapshot de parâmetros.

NÃO depende de NJ6/Endpoint (caminho de leitura — ver `service_buscar.py`) nem de metadados
de auditoria/original/vigente: confirmado com o PO que as regras R1/R2/R3 (`domain/eleicao.py`)
só se aplicam à eleição sobre as análises cruas do Endpoint, nunca a um registro do nosso
banco — o SALVAR não tem como saber se um valor digitado foi "auditado" ou qual a categoria
do balanço, então nem tenta. Emite eventos de NEGÓCIO para o Datadog (divergência barrada,
faturamento persistido) — sem ruído.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Protocol

from app.core.logging import get_logger, log_event
from app.domain import divergencia
from app.domain.errors import ConfirmacaoNecessaria, ErroValidacao, FaixaObrigatoria
from app.domain.faixa import de_para_valor_para_faixa, valor_em_reais
from app.domain.models import Faturamento, MarcadorFaturamento, Nivel, Origem

_logger = get_logger("faturamento.service")


class Repositorio(Protocol):
    def get_subgrupo(
        self, conglomerado_doc: str, subgrupo_doc: str
    ) -> Optional[MarcadorFaturamento]: ...
    def save(self, f: Faturamento) -> None: ...


def salvar(fat: Faturamento, repo: Repositorio, params: dict) -> Faturamento:
    """Valida e grava o agregado. `params` = snapshot do serviço de parâmetros."""
    if not fat.marcadores:
        raise ErroValidacao("Nenhum marcador informado para classificar.")

    faixas = params.get("faixas") or []
    moedas = {m.upper() for m in (params.get("moedas") or [])}

    divergencias: list[dict] = []
    for m in fat.marcadores:
        _normalizar(m, fat)
        _validar_marcador(m, faixas)
        _validar_moeda(m, moedas)
        divergencias.extend(_avaliar_gate(m, fat, repo, params))

    if divergencias:
        log_event(
            _logger,
            "faturamento.divergencia_barrada",
            level="warning",
            conglomerado_doc=fat.conglomerado_doc,
            qtd_divergencias=len(divergencias),
        )
        raise ConfirmacaoNecessaria(divergencias)

    fat.atualizado_em = _agora()
    repo.save(fat)
    _log_persistido(fat)
    return fat


# ────── etapas ──────


def _normalizar(m: MarcadorFaturamento, fat: Faturamento) -> None:
    """Coerência da chave: todo marcador pertence ao conglomerado do agregado."""
    m.conglomerado_doc = fat.conglomerado_doc
    m.nivel = Nivel.CONGLOMERADO if m.e_matriz else Nivel.SUBGRUPO
    m.origem = Origem.BASE  # gravar na nossa base => o dado passa a ser BASE


def _validar_marcador(m: MarcadorFaturamento, faixas: list[dict]) -> None:
    """De-para automático valor→faixa; faixa obrigatória se não houver valor específico."""
    if not m.subgrupo_doc:
        raise ErroValidacao("subgrupoDoc obrigatório no marcador.")
    if m.sem_faturamento:
        m.atual.valor = None  # "Não possuo o faturamento": sem valor e sem faixa, sem de-para
        m.atual.faixa_codigo = None
        return
    if not faixas:
        raise ErroValidacao("Catálogo de faixas indisponível no serviço de parâmetros.")

    info = m.atual
    if info.valor is not None:
        valor_reais = valor_em_reais(info.valor, info.unidade)
        if valor_reais is None:
            raise ErroValidacao(
                f"Unidade desconhecida para o subgrupo {m.subgrupo_doc}: {info.unidade!r}."
            )
        faixa = de_para_valor_para_faixa(valor_reais, faixas)
        if faixa is None:
            raise ErroValidacao(f"Valor {info.valor} ({info.unidade}) fora das faixas conhecidas.")
        info.faixa_codigo = faixa
    elif not info.faixa_codigo:
        raise FaixaObrigatoria(f"Subgrupo {m.subgrupo_doc}: informe valor específico ou faixa.")


def _validar_moeda(m: MarcadorFaturamento, moedas: set[str]) -> None:
    """Moeda obrigatória e presente no catálogo de parâmetros."""
    if m.sem_faturamento:
        return  # sem valor -> moeda não se aplica
    moeda = m.atual.moeda
    if not moeda:
        raise ErroValidacao(f"Moeda obrigatória para o subgrupo {m.subgrupo_doc}.")
    if not moedas:
        raise ErroValidacao("Catálogo de moedas indisponível no serviço de parâmetros.")
    if moeda.upper() not in moedas:
        raise ErroValidacao(f"Moeda inválida ({moeda}) para o subgrupo {m.subgrupo_doc}.")


def _avaliar_gate(
    m: MarcadorFaturamento, fat: Faturamento, repo: Repositorio, params: dict
) -> list[dict]:
    """Gate de divergência (síncrono, ANTES de gravar): compara com o que já está salvo."""
    gate_ativo = bool(params.get("gateDivergenciaAtivo", False))
    if not gate_ativo or m.confirmado_divergencia:
        return []
    existente = repo.get_subgrupo(fat.conglomerado_doc, m.subgrupo_doc)
    if existente is None:
        return []
    limite_pct = int(params.get("limiteVariacaoPercentual", 0))
    return divergencia.avaliar(m, existente, limite_pct)


# ────── internos ──────


def _agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _log_persistido(fat: Faturamento) -> None:
    log_event(
        _logger,
        "faturamento.persistido",
        conglomerado_doc=fat.conglomerado_doc,
        qtd_marcadores=len(fat.marcadores),
        snapshots_spread=sum(1 for m in fat.marcadores if m.atual and m.atual.id_spread),
        sistemas_origem=sorted(
            {m.atual.sistema_origem for m in fat.marcadores if m.atual and m.atual.sistema_origem}
        ),
    )
