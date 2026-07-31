from datetime import date
from decimal import Decimal

from app.domain.eleicao import eleger

ASOF = date(2024, 6, 1)


def _analise(
    *,
    codigo=1,
    auditado=True,
    original=True,
    vigente=True,
    situacao_codigo=3,
    categoria_codigo=2,
    data_referencia="2024-01-01",
    valor=5_000_000,
    atualizado="2024-01-02",
):
    return {
        "codigo": codigo,
        "auditoria": {"possuiAuditoria": auditado},
        "indicadorFatorPonderado": original,  # original ⇔ indicadorFatorPonderado is True
        "indicadorVigente": {"descricao": "Ativo" if vigente else "Inativo"},
        "situacao": {"codigo": situacao_codigo},
        "categoria": {"codigo": categoria_codigo},
        "faturamento": [{"dataReferencia": data_referencia, "valor": valor}],
        # nome real confirmado numa fixture de resposta do Endpoint: "atualizacao", não "atualizado".
        "atualizacao": atualizado,
    }


def test_r1_elege_quando_auditado_original_vigente_e_categoria_prioritaria():
    analise = _analise(categoria_codigo=2)  # categoria elegível na R1
    resultado = eleger([analise], ASOF)
    assert resultado is not None
    assert resultado.valor_faturamento == Decimal("5000000")
    assert resultado.data_ref_balanco == "2024-01-01"


def test_r1_desempata_por_prioridade_de_categoria():
    # PRIORIDADE_CATEGORIA_R1 = (2, 4, 3, 5, 6) — categoria 2 tem prioridade sobre 4.
    menos_prioritaria = _analise(codigo=1, categoria_codigo=4, valor=1_000_000)
    mais_prioritaria = _analise(codigo=2, categoria_codigo=2, valor=2_000_000)
    resultado = eleger([menos_prioritaria, mais_prioritaria], ASOF)
    assert resultado.valor_faturamento == Decimal("2000000")


def test_r1_desempata_por_atualizacao_mais_recente_quando_mesma_categoria():
    mais_antiga = _analise(codigo=1, categoria_codigo=2, atualizado="2024-01-01", valor=1_000_000)
    mais_recente = _analise(codigo=2, categoria_codigo=2, atualizado="2024-03-01", valor=2_000_000)
    resultado = eleger([mais_antiga, mais_recente], ASOF)
    assert resultado.valor_faturamento == Decimal("2000000")


def test_r1_le_atualizacao_com_o_nome_real_do_campo_do_endpoint():
    """Regressão: o campo real que o Endpoint devolve é "atualizacao", não
    "atualizado" - confirmado numa fixture de resposta real. Usa dicts crus (sem
    passar por `_analise`) para não mascarar um possível retorno ao nome errado."""
    mais_antiga = {
        "codigo": 1,
        "auditoria": {"possuiAuditoria": True},
        "indicadorFatorPonderado": True,
        "indicadorVigente": {"descricao": "Ativo"},
        "situacao": {"codigo": 3},
        "categoria": {"codigo": 2},
        "faturamento": [{"dataReferencia": "2024-01-01", "valor": 1_000_000}],
        "atualizacao": "2023-01-01T00:00:00",
    }
    mais_recente = {
        "codigo": 2,
        "auditoria": {"possuiAuditoria": True},
        "indicadorFatorPonderado": True,
        "indicadorVigente": {"descricao": "Ativo"},
        "situacao": {"codigo": 3},
        "categoria": {"codigo": 2},
        "faturamento": [{"dataReferencia": "2024-01-01", "valor": 2_000_000}],
        "atualizacao": "2024-06-15T14:30:00",
    }
    resultado = eleger([mais_antiga, mais_recente], ASOF)
    assert resultado.valor_faturamento == Decimal("2000000")


def test_r2_elege_quando_r1_nao_qualifica_por_categoria():
    # categoria fora da lista de prioridade da R1 (ex.: 1 = Individual) -> cai pra R2.
    analise = _analise(categoria_codigo=1, situacao_codigo=3)
    resultado = eleger([analise], ASOF)
    assert resultado is not None
    assert resultado.valor_faturamento == Decimal("5000000")


def test_r2_desempata_pelo_balanco_mais_recente():
    mais_antigo = _analise(
        codigo=1, categoria_codigo=1, data_referencia="2024-01-01", valor=1_000_000
    )
    mais_recente = _analise(
        codigo=2, categoria_codigo=1, data_referencia="2024-03-01", valor=2_000_000
    )
    resultado = eleger([mais_antigo, mais_recente], ASOF)
    assert resultado.valor_faturamento == Decimal("2000000")


def test_r3_elege_quando_r1_e_r2_nao_qualificam():
    # auditado=False (falha R1 e R2), original=True + vigente + Aprovado(3), categoria não excluída.
    analise = _analise(auditado=False, categoria_codigo=2, situacao_codigo=3)
    resultado = eleger([analise], ASOF)
    assert resultado is not None
    assert resultado.valor_faturamento == Decimal("5000000")


def test_r3_desempata_pelo_maior_valor():
    menor = _analise(codigo=1, auditado=False, categoria_codigo=2, valor=1_000_000)
    maior = _analise(codigo=2, auditado=False, categoria_codigo=2, valor=9_000_000)
    resultado = eleger([menor, maior], ASOF)
    assert resultado.valor_faturamento == Decimal("9000000")


def test_r3_exclui_categorias_individuais_e_combinadas():
    # categoria 1 (Individual) é excluída da R3; sem auditado (falha R1/R2) -> nenhuma regra passa.
    analise = _analise(auditado=False, categoria_codigo=1)
    resultado = eleger([analise], ASOF)
    assert resultado is None


def test_nenhuma_regra_passa_retorna_none():
    analise = _analise(auditado=False, original=False, vigente=False)
    resultado = eleger([analise], ASOF)
    assert resultado is None


def test_balanco_fora_da_janela_de_24_meses_e_ignorado():
    analise = _analise(data_referencia="2020-01-01")  # > 24 meses antes de ASOF
    resultado = eleger([analise], ASOF)
    assert resultado is None


def test_lista_vazia_retorna_none():
    assert eleger([], ASOF) is None


def test_categoria_nao_numerica_e_tratada_como_ausente():
    """codigo.categoria não-numérico (ex.: payload malformado) -> _codigo() devolve None
    em vez de levantar - a análise só perde elegibilidade na R1 (categoria exigida)."""
    analise = _analise(categoria_codigo="abc", situacao_codigo=3)
    resultado = eleger([analise], ASOF)
    assert resultado is not None  # cai pra R2 (auditado+vigente+aprovado)


def test_meses_entre_desconta_um_mes_quando_dia_do_fim_e_menor():
    """31/01 -> 10/06: 5 meses "de calendário", mas o dia 10 < dia 31 - ainda não completou
    o 5º mês, então desconta 1 (equivalente a ChronoUnit.MONTHS.between)."""
    analise = _analise(data_referencia="2024-01-31")
    resultado = eleger([analise], date(2024, 6, 10))
    assert resultado is not None


# ────────────────────────────────────────────────────────────────────────────
# Casos de borda adicionais - motivados pelo bug real de "atualizacao" vs
# "atualizado": todo campo lido de um payload do Endpoint merece um teste que
# prove o comportamento com a chave ausente/nula, não só com o valor "feliz".
# ────────────────────────────────────────────────────────────────────────────


def test_r1_prioridade_categoria_ordem_completa_categoria2_vence_todas():
    # PRIORIDADE_CATEGORIA_R1 = (2, 4, 3, 5, 6) - categoria 2 é a de maior prioridade.
    candidatos = [
        _analise(codigo=1, categoria_codigo=4, valor=100),
        _analise(codigo=2, categoria_codigo=3, valor=200),
        _analise(codigo=3, categoria_codigo=5, valor=300),
        _analise(codigo=4, categoria_codigo=6, valor=400),
        _analise(codigo=5, categoria_codigo=2, valor=500),
    ]
    resultado = eleger(candidatos, ASOF)
    assert resultado.valor_faturamento == Decimal("500")  # categoria 2 venceu as outras 4


def test_r1_prioridade_categoria_sem_categoria2_categoria4_vence():
    # sem a categoria 2 na disputa, a próxima prioridade (4) deve vencer 3/5/6.
    candidatos = [
        _analise(codigo=1, categoria_codigo=3, valor=200),
        _analise(codigo=2, categoria_codigo=5, valor=300),
        _analise(codigo=3, categoria_codigo=6, valor=400),
        _analise(codigo=4, categoria_codigo=4, valor=100),
    ]
    resultado = eleger(candidatos, ASOF)
    assert resultado.valor_faturamento == Decimal("100")  # categoria 4 venceu 3/5/6


def test_r1_desempate_cai_pra_data_ref_quando_categoria_e_atualizado_empatam():
    # mesma categoria e mesma data de atualização -> desempate final é a data do balanço.
    mais_antigo = _analise(
        codigo=1, categoria_codigo=2, atualizado="2024-01-02", data_referencia="2024-01-01", valor=1
    )
    mais_recente = _analise(
        codigo=2, categoria_codigo=2, atualizado="2024-01-02", data_referencia="2024-03-01", valor=2
    )
    resultado = eleger([mais_antigo, mais_recente], ASOF)
    assert resultado.valor_faturamento == Decimal("2")


def test_auditoria_ausente_e_tratado_como_nao_auditado():
    """Sem a chave "auditoria", `_auditado` deve tratar como False - prova isso
    combinando com categoria 6 (elegível em R1, mas EXCLUÍDA em R3): se
    "auditoria ausente" fosse tratado como True por engano, R1 elegeria; se
    fosse tratado certo (False), nem R1 nem R3 (excluída) sobra, e o resultado
    é None."""
    analise = {
        "codigo": 1,
        "indicadorFatorPonderado": True,
        "indicadorVigente": {"descricao": "Ativo"},
        "situacao": {"codigo": 3},
        "categoria": {"codigo": 6},
        "faturamento": [{"dataReferencia": "2024-01-01", "valor": 5_000_000}],
        "atualizacao": "2024-01-02",
    }
    assert eleger([analise], ASOF) is None


def test_possuiauditoria_none_e_tratado_como_nao_auditado():
    analise = _analise(categoria_codigo=6)
    analise["auditoria"] = {"possuiAuditoria": None}
    assert eleger([analise], ASOF) is None  # mesma lógica do teste anterior


def test_indicadorfatorponderado_ausente_e_tratado_como_nao_original():
    """Sem "indicadorFatorPonderado", `_original` deve ser False - combinado com
    auditado=False (falha R1/R2) e categoria não excluída, R3 também exige
    original=True, então o resultado tem que ser None."""
    analise = {
        "codigo": 1,
        "auditoria": {"possuiAuditoria": False},
        "indicadorVigente": {"descricao": "Ativo"},
        "situacao": {"codigo": 3},
        "categoria": {"codigo": 2},
        "faturamento": [{"dataReferencia": "2024-01-01", "valor": 5_000_000}],
        "atualizacao": "2024-01-02",
    }
    assert eleger([analise], ASOF) is None


def test_indicadorvigente_ausente_e_tratado_como_nao_vigente():
    """`vigente` é exigido nas 3 regras - sem "indicadorVigente", nenhuma passa."""
    analise = {
        "codigo": 1,
        "auditoria": {"possuiAuditoria": True},
        "indicadorFatorPonderado": True,
        "situacao": {"codigo": 3},
        "categoria": {"codigo": 2},
        "faturamento": [{"dataReferencia": "2024-01-01", "valor": 5_000_000}],
        "atualizacao": "2024-01-02",
    }
    assert eleger([analise], ASOF) is None


def test_vigente_aceita_variacoes_de_caixa_do_texto_ativo():
    for texto in ("Ativo", "ATIVO", "ativo", "AtIvO"):
        analise = _analise(categoria_codigo=2)
        analise["indicadorVigente"] = {"descricao": texto}
        assert eleger([analise], ASOF) is not None, f"deveria aceitar {texto!r}"


def test_situacao_codigo_4_historico_aprovado_nao_conta_como_aprovado():
    """`situacao.codigo == 4` ("Histórico Aprovado") NÃO é Aprovado - falha R2 e R3."""
    analise = _analise(auditado=False, categoria_codigo=2, situacao_codigo=4)
    assert eleger([analise], ASOF) is None


def test_situacao_ausente_nao_e_aprovado():
    analise = {
        "codigo": 1,
        "auditoria": {"possuiAuditoria": False},
        "indicadorFatorPonderado": True,
        "indicadorVigente": {"descricao": "Ativo"},
        "categoria": {"codigo": 2},
        "faturamento": [{"dataReferencia": "2024-01-01", "valor": 5_000_000}],
        "atualizacao": "2024-01-02",
    }
    assert eleger([analise], ASOF) is None  # não auditado (falha R1/R2) e não aprovado (falha R3)


def test_categoria_ausente_e_tratada_como_none():
    """Sem a chave "categoria" (não apenas um código não-numérico) - mesma
    degradação de `test_categoria_nao_numerica_e_tratada_como_ausente`: perde
    R1 (exige categoria na lista), mas ainda pode passar em R2."""
    analise = {
        "codigo": 1,
        "auditoria": {"possuiAuditoria": True},
        "indicadorFatorPonderado": True,
        "indicadorVigente": {"descricao": "Ativo"},
        "situacao": {"codigo": 3},
        "faturamento": [{"dataReferencia": "2024-01-01", "valor": 5_000_000}],
        "atualizacao": "2024-01-02",
    }
    resultado = eleger([analise], ASOF)
    assert resultado is not None  # cai pra R2 (auditado+vigente+aprovado, sem exigir categoria)


def test_categoria_6_elegivel_em_r1_quando_auditado():
    # categoria 6 (Matriz Individual) está em PRIORIDADE_CATEGORIA_R1 (última posição).
    analise = _analise(categoria_codigo=6, valor=7_000_000)
    resultado = eleger([analise], ASOF)
    assert resultado.valor_faturamento == Decimal("7000000")


def test_categoria_6_falha_r1_e_r3_quando_nao_auditado():
    """Categoria 6 está em AMBAS as listas: elegível em R1 (prioridade), mas
    EXCLUÍDA em R3. Sem auditado, falha R1/R2; e falha R3 pela exclusão -
    prova que a mesma categoria pode ser "boa" pra uma regra e "ruim" pra outra."""
    analise = _analise(auditado=False, categoria_codigo=6)
    assert eleger([analise], ASOF) is None


def test_r3_exclui_categoria_7_combinado():
    analise = _analise(auditado=False, categoria_codigo=7)
    assert eleger([analise], ASOF) is None


def test_r3_exclui_categoria_8_combinado():
    analise = _analise(auditado=False, categoria_codigo=8)
    assert eleger([analise], ASOF) is None


def test_r3_exclui_categoria_9_combinado():
    analise = _analise(auditado=False, categoria_codigo=9)
    assert eleger([analise], ASOF) is None


def test_r3_nao_exclui_categoria_3():
    analise = _analise(auditado=False, categoria_codigo=3, valor=3_000_000)
    resultado = eleger([analise], ASOF)
    assert resultado.valor_faturamento == Decimal("3000000")


def test_r3_nao_exclui_categoria_5():
    analise = _analise(auditado=False, categoria_codigo=5, valor=5_500_000)
    resultado = eleger([analise], ASOF)
    assert resultado.valor_faturamento == Decimal("5500000")


def test_balanco_exatamente_24_meses_e_elegivel():
    analise = _analise(data_referencia="2022-06-01")  # exatamente 24 meses antes de ASOF
    resultado = eleger([analise], ASOF)
    assert resultado is not None


def test_balanco_25_meses_e_inelegivel():
    analise = _analise(data_referencia="2022-05-01")  # 25 meses antes de ASOF
    resultado = eleger([analise], ASOF)
    assert resultado is None


def test_balanco_data_futura_e_descartado():
    analise = _analise(data_referencia="2024-07-01")  # depois de ASOF (2024-06-01)
    resultado = eleger([analise], ASOF)
    assert resultado is None


def test_analise_com_faturamento_vazio_nao_e_candidata():
    analise = _analise()
    analise["faturamento"] = []
    assert eleger([analise], ASOF) is None


def test_analise_sem_faturamento_nao_e_candidata():
    analise = _analise()
    del analise["faturamento"]
    assert eleger([analise], ASOF) is None


def test_escolhe_balanco_mais_recente_dentro_da_mesma_analise():
    """Uma única análise pode ter vários balanços no histórico - o mais
    recente dentro da janela é o que vale, não o primeiro da lista."""
    analise = _analise()
    analise["faturamento"] = [
        {"dataReferencia": "2024-01-01", "valor": 1_000_000},
        {"dataReferencia": "2024-03-01", "valor": 2_000_000},
    ]
    resultado = eleger([analise], ASOF)
    assert resultado.valor_faturamento == Decimal("2000000")
    assert resultado.data_ref_balanco == "2024-03-01"


def test_eleger_extrai_unidade_e_moeda_do_payload_real_do_endpoint():
    """Formato exato confirmado numa fixture de resposta real: objetos aninhados
    {"codigo", "descricao", ...}, não strings soltas."""
    analise = _analise()
    analise["unidade"] = {"codigo": "1", "descricao": "Mil", "valor": 1000}
    analise["moeda"] = {"codigo": "180300790", "descricao": "BRL"}
    resultado = eleger([analise], ASOF)
    assert resultado.unidade == "Mil"
    assert resultado.moeda == "BRL"


def test_moeda_ausente_usa_fallback_brl():
    analise = _analise()
    resultado = eleger([analise], ASOF)
    assert resultado.moeda == "BRL"


def test_unidade_ausente_usa_fallback_milhoes():
    analise = _analise()
    resultado = eleger([analise], ASOF)
    assert resultado.unidade == "milhoes"


def test_id_spread_e_o_codigo_da_analise_convertido_pra_string():
    analise = _analise(codigo=2097)
    resultado = eleger([analise], ASOF)
    assert resultado.id_spread == "2097"


def test_id_spread_none_quando_codigo_ausente():
    analise = _analise()
    del analise["codigo"]
    resultado = eleger([analise], ASOF)
    assert resultado.id_spread is None


def test_situacao_codigo_1_nao_e_aprovado():
    # categoria fora da lista de R1 (perde por categoria); situacao=1 não é Aprovado -> falha R2/R3.
    analise = _analise(categoria_codigo=1, situacao_codigo=1)
    assert eleger([analise], ASOF) is None


def test_situacao_codigo_2_nao_e_aprovado():
    analise = _analise(categoria_codigo=1, situacao_codigo=2)
    assert eleger([analise], ASOF) is None


def test_r1_categoria_fora_da_lista_cai_pra_r2_mesmo_auditado():
    # categoria 7 não está em PRIORIDADE_CATEGORIA_R1 -> falha R1 mesmo com tudo auditado/original/vigente.
    analise = _analise(categoria_codigo=7, valor=6_000_000)
    resultado = eleger([analise], ASOF)
    assert resultado.valor_faturamento == Decimal("6000000")  # eleito por R2


def test_r3_desempate_entre_tres_candidatos_pelo_maior_valor():
    candidatos = [
        _analise(codigo=1, auditado=False, categoria_codigo=2, valor=1_000_000),
        _analise(codigo=2, auditado=False, categoria_codigo=2, valor=9_000_000),
        _analise(codigo=3, auditado=False, categoria_codigo=2, valor=5_000_000),
    ]
    resultado = eleger(candidatos, ASOF)
    assert resultado.valor_faturamento == Decimal("9000000")


def test_valor_como_string_numerica_e_convertido_pra_decimal():
    analise = _analise()
    analise["faturamento"] = [{"dataReferencia": "2024-01-01", "valor": "5000000.00"}]
    resultado = eleger([analise], ASOF)
    assert resultado.valor_faturamento == Decimal("5000000.00")


def test_multiplas_analises_nenhuma_elegivel_retorna_none():
    candidatos = [
        _analise(codigo=1, auditado=False, original=False, vigente=False),
        _analise(codigo=2, auditado=False, original=False, vigente=False),
    ]
    assert eleger(candidatos, ASOF) is None
