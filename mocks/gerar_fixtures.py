#!/usr/bin/env python3
"""Gera `mocks/app/fixtures/{nj6,endpoint}.json` + `docs/CASOS_TESTE_MOCK.md`
a partir de UMA fonte única (`CASOS`, abaixo) — evita fixture e doc saírem
dessincronizados (mesma lição do `scripts/checar_docs_atualizados.py`).

Uso:
    python3 mocks/gerar_fixtures.py

Convenção de documento (raiz, sem dígito verificador — só dígitos, 9 posições):
    matriz do caso N        -> "900{N:03d}000"
    subgrupo K do caso N    -> "900{N:03d}{K:03d}"   (K >= 1)

O caso legado "COSAN" (doc "050746577") é preservado à parte, fora da faixa
"900...", porque já tinha sido usado em teste manual/POST antes desses 20
casos existirem — ver docs/CASOS_TESTE_MOCK.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).parent
FIXTURES = ROOT / "app" / "fixtures"
DOC_OUT = ROOT.parent / "docs" / "CASOS_TESTE_MOCK.md"

CATEGORIA_NOME = {
    1: "Individual",
    2: "Consolidado-Subgrupo Todo",
    3: "Consolidado-Segmento Específico",
    4: "Matriz Consolidado-Subgrupo Todo",
    5: "Matriz Consolidado-Segmento Específico",
    6: "Matriz Individual",
    7: "Combinado A",
    8: "Combinado B",
    9: "Combinado C",
}


def doc_matriz(n: int) -> str:
    return f"900{n:03d}000"


def doc_sub(n: int, k: int) -> str:
    return f"900{n:03d}{k:03d}"


@dataclass
class Analise:
    codigo: int
    categoria: int
    auditado: bool
    original: bool  # indicadorFatorPonderado
    vigente: bool = True
    aprovado: bool = True  # situacao == 3 (Aprovado)
    valor: float = 1_000
    unidade_codigo: str = "1"
    unidade_nome: str = "Mil"
    unidade_valor: int = 1_000
    moeda: str = "BRL"
    data_ref: str = "2024-12-31"
    atualizacao: str = "2024-06-15T10:00:00"

    def to_json(self, doc_grupo: str) -> dict:
        return {
            "codigo": self.codigo,
            "nome": f"Análise {self.codigo}",
            "etapa": None,
            "situacao": {"codigo": 3 if self.aprovado else 4, "descricao": "Aprovado" if self.aprovado else "Histórico Aprovado"},
            "indicadorVigente": {"codigo": 1 if self.vigente else 2, "descricao": "Ativo" if self.vigente else "Inativo"},
            "categoria": {"codigo": self.categoria, "descricao": CATEGORIA_NOME[self.categoria]},
            "unidade": {"codigo": self.unidade_codigo, "descricao": self.unidade_nome, "valor": self.unidade_valor},
            "subgrupo": doc_grupo,
            "conglomerado": doc_grupo,
            "moeda": {"codigo": "180300790" if self.moeda == "BRL" else "180300791", "descricao": self.moeda},
            "grupoEmpresa": {"codigo": 763, "nome": "OUTROS", "prospect": {"codigo": 1, "nome": "Cliente"}},
            "auditoria": {
                "codigo": 1,
                "dataCriacao": "2023-04-20T22:33:43",
                "possuiAuditoria": self.auditado,
                "entradaManual": False,
            },
            "faturamento": [{"dataReferencia": self.data_ref, "valor": self.valor}],
            "atualizacao": self.atualizacao,
            "indicadorFatorPonderado": self.original,
        }


def r1(codigo: int, categoria: int, valor: float, **kw) -> Analise:
    """Auditado + original + vigente — só entra na R1 se `categoria` estiver na lista de
    prioridade (2, 4, 3, 5, 6)."""
    return Analise(codigo=codigo, categoria=categoria, auditado=True, original=True, valor=valor, **kw)


def r2(codigo: int, valor: float, categoria: int = 1, **kw) -> Analise:
    """Auditado + vigente + aprovado, NÃO original — nunca ganha na R1, só na R2."""
    return Analise(codigo=codigo, categoria=categoria, auditado=True, original=False, valor=valor, **kw)


def r3(codigo: int, valor: float, categoria: int = 2, **kw) -> Analise:
    """Original + vigente + aprovado, NÃO auditado, categoria fora da lista excluída da R3
    ({1, 6, 7, 8, 9}) — nunca ganha R1 (falta auditoria), nunca ganha R2 (idem), só R3."""
    return Analise(codigo=codigo, categoria=categoria, auditado=False, original=True, valor=valor, **kw)


@dataclass
class SubgrupoDef:
    nome: str
    doc: str
    analises: list[Analise] = field(default_factory=list)


@dataclass
class Caso:
    n: int
    nome_grupo: str
    objetivo: str
    roteiro: str
    matriz_analises: list[Analise] = field(default_factory=list)
    subgrupos: list[SubgrupoDef] = field(default_factory=list)
    segmento: str | None = None
    nome_subgrupo_matriz: str = "OUTROS"
    # dedup: doc alternativo pro segundo subgrupo "espelhar" (casos 18/19)
    dedup_extra: SubgrupoDef | None = None


CASOS: list[Caso] = []


def _add(caso: Caso) -> None:
    CASOS.append(caso)


# ────────────────────────── 01 ──────────────────────────
_add(Caso(
    n=1,
    nome_grupo="Alfa Comércio e Distribuição S.A.",
    segmento="Varejo",
    objetivo="Caso mais simples: só matriz, 1 análise R1 válida. GET puro, sem precisar salvar nada antes.",
    roteiro="Buscar o CNPJ — o faturamento já aparece resolvido pelo Endpoint (origem ENDPOINT), faixa \"5 Bi a 10 Bi\".",
    matriz_analises=[r1(codigo=1001, categoria=2, valor=8_000_000)],  # 8.000.000 Mil = 8 Bi
))

# ────────────────────────── 02 ──────────────────────────
_add(Caso(
    n=2,
    nome_grupo="Beta Participações Ltda",
    objetivo="Cascata completa R1/R2/R3 dentro do mesmo conglomerado — matriz usa R1, sub 1 usa R2, sub 2 usa R3.",
    roteiro="Buscar o CNPJ — confira que os 3 níveis (matriz + 2 subgrupos) resolvem por regras diferentes (dá pra ver pelo idSpread/valor de cada um, a API não expõe qual regra venceu diretamente).",
    matriz_analises=[r1(codigo=1010, categoria=4, valor=1_200_000)],  # 1,2 Bi -> 1_bi_2_5_bi
    subgrupos=[
        SubgrupoDef("Beta Norte", doc_sub(2, 1), [r2(codigo=1011, valor=15_000)]),  # 15 MM -> 4_8_mm_20_mm
        SubgrupoDef("Beta Sul", doc_sub(2, 2), [r3(codigo=1012, valor=600_000)]),  # 600 MM -> 500_mm_1_bi
    ],
))

# ────────────────────────── 03 ──────────────────────────
_add(Caso(
    n=3,
    nome_grupo="Gamma Indústria e Comércio S.A.",
    objetivo="8 subgrupos, sendo 4 com dado no Endpoint e 4 SEM NADA (MANUAL) — mistura dentro do mesmo conglomerado.",
    roteiro="Buscar o CNPJ — metade das linhas já vem preenchida (ENDPOINT), a outra metade fica em branco pra você preencher manualmente e salvar.",
    matriz_analises=[r1(codigo=1020, categoria=2, valor=25_000)],  # 25 MM -> 20_mm_125_mm
    subgrupos=[
        SubgrupoDef("Gamma Norte", doc_sub(3, 1), [r1(codigo=1021, categoria=2, valor=500)]),  # 500 mil -> 360_mil_4_8_mm
        SubgrupoDef("Gamma Sul", doc_sub(3, 2), [r1(codigo=1022, categoria=2, valor=50_000)]),  # 50 MM -> 20_mm_125_mm
        SubgrupoDef("Gamma Leste", doc_sub(3, 3), [r1(codigo=1023, categoria=2, valor=2_000_000)]),  # 2 Bi -> 1_bi_2_5_bi
        SubgrupoDef("Gamma Oeste", doc_sub(3, 4), [r1(codigo=1024, categoria=2, valor=200)]),  # 200 mil -> ate_360_mil
        SubgrupoDef("Gamma Centro", doc_sub(3, 5), []),  # sem endpoint -> MANUAL
        SubgrupoDef("Gamma Litoral", doc_sub(3, 6), []),
        SubgrupoDef("Gamma Interior", doc_sub(3, 7), []),
        SubgrupoDef("Gamma Fronteira", doc_sub(3, 8), []),
    ],
))

# ────────────────────────── 04 ──────────────────────────
_valores_delta = [100, 900, 10_000, 60_000, 200_000, 400_000, 800_000, 1_800_000, 3_500_000, 7_000_000]
_add(Caso(
    n=4,
    nome_grupo="Delta Holding Multinegócios S.A.",
    segmento="Atacado",
    objetivo="16 subgrupos — o MÁXIMO permitido no NJ6. 10 com dado no Endpoint (faixas bem espalhadas), 6 em MANUAL.",
    roteiro="Buscar o CNPJ — stress-test de volume/scroll da tela única (17 linhas: matriz + 16 subgrupos).",
    matriz_analises=[r1(codigo=1030, categoria=2, valor=12_000_000)],  # 12 Bi -> acima_10_bi
    subgrupos=[
        SubgrupoDef(f"Delta Unidade {k:02d}", doc_sub(4, k),
                     [r1(codigo=1030 + k, categoria=2, valor=_valores_delta[k - 1])] if k <= 10 else [])
        for k in range(1, 17)
    ],
))

# ────────────────────────── 05 ──────────────────────────
_add(Caso(
    n=5,
    nome_grupo="Épsilon Comércio Varejista Ltda",
    objetivo="Só matriz, ZERO dado no Endpoint — o caso mais simples de \"salvar e depois buscar\" (modo \"Por valor\").",
    roteiro="Buscar (vem tudo MANUAL/vazio) -> abrir \"Atualizar\", preencher \"Por valor\" -> salvar -> buscar de novo (agora vem BASE).",
))

# ────────────────────────── 06 ──────────────────────────
_add(Caso(
    n=6,
    nome_grupo="Zeta Agroindustrial S.A.",
    objetivo="Matriz + 4 subgrupos, NENHUM no Endpoint — \"salvar depois buscar\" em lote (5 marcadores de uma vez).",
    roteiro="Buscar (5 linhas vazias) -> preencher e salvar cada uma (pode confirmar_divergencia se reenviar) -> buscar de novo.",
    subgrupos=[SubgrupoDef(f"Zeta Regional {k}", doc_sub(6, k), []) for k in range(1, 5)],
))

# ────────────────────────── 07 ──────────────────────────
_add(Caso(
    n=7,
    nome_grupo="Eta Serviços Financeiros S.A.",
    objetivo="Subgrupo TEM análise no Endpoint, mas indicadorVigente=Inativo — não elege em nenhuma regra (R1/R2/R3 exigem vigente), cai em MANUAL mesmo \"tendo algo\".",
    roteiro="Buscar — a matriz vem preenchida (ENDPOINT), o subgrupo fica vazio mesmo existindo uma análise pra ele (edge case: \"tem mas não conta\").",
    matriz_analises=[r1(codigo=1050, categoria=2, valor=5_000)],  # 5 MM -> 4_8_mm_20_mm
    subgrupos=[
        SubgrupoDef("Eta Crédito", doc_sub(7, 1), [
            Analise(codigo=1051, categoria=2, auditado=True, original=True, vigente=False, valor=9_999_999),
        ]),
    ],
))

# ────────────────────────── 08 ──────────────────────────
_add(Caso(
    n=8,
    nome_grupo="Theta Engenharia e Construção S.A.",
    objetivo="1 análise válida em tudo (auditada/original/vigente/aprovada) mas com balanço de 2019 — fora da janela de 24 meses. Sem balanço vigente -> MANUAL.",
    roteiro="Buscar — vem vazio mesmo tendo uma análise \"completa\" no Endpoint (edge case de idade/vigência temporal).",
    matriz_analises=[r1(codigo=1060, categoria=2, valor=3_000_000, data_ref="2019-03-31")],
))

# ────────────────────────── 09 ──────────────────────────
_add(Caso(
    n=9,
    nome_grupo="Iota Mineração S.A.",
    objetivo="3 análises concorrendo pela R1 com categorias diferentes (6, 3, 2) — testa o desempate por PRIORIDADE_CATEGORIA_R1 (categoria 2 tem que ganhar, mesmo não sendo a de maior valor).",
    roteiro="Buscar — confira que o valor resolvido é o da categoria 2 (100 MM -> faixa 20_mm_125_mm), não o maior valor (categoria 6, quase 1 Bi).",
    matriz_analises=[
        r1(codigo=1070, categoria=6, valor=999_999),  # maior valor, mas categoria de MENOR prioridade
        r1(codigo=1071, categoria=3, valor=500_000),
        r1(codigo=1072, categoria=2, valor=100_000),  # deve vencer (categoria de maior prioridade)
    ],
))

# ────────────────────────── 10 ──────────────────────────
_add(Caso(
    n=10,
    nome_grupo="Capa Logística Integrada S.A.",
    objetivo="2 análises R1 na MESMA categoria — desempate por data de atualização mais recente.",
    roteiro="Buscar — confira que vence a análise mais recente (atualizacao 2024-06-20), valor 9 MM -> faixa 4_8_mm_20_mm, não a de 2024-01-10.",
    matriz_analises=[
        r1(codigo=1080, categoria=2, valor=1_000, atualizacao="2024-01-10T09:00:00"),  # 1 MM -> 360_mil_4_8_mm
        r1(codigo=1081, categoria=2, valor=9_000, atualizacao="2024-06-20T09:00:00"),  # mais recente, deve vencer
    ],
))

# ────────────────────────── 11 ──────────────────────────
_add(Caso(
    n=11,
    nome_grupo="Lambda Farmacêutica S.A.",
    objetivo="Moeda USD (não BRL) vinda do Endpoint — variabilidade de moeda.",
    roteiro="Buscar — confira que \"moeda\" vem \"USD\" no marcador resolvido pelo Endpoint.",
    matriz_analises=[r1(codigo=1090, categoria=2, valor=4_000, moeda="USD")],  # 4 MM USD -> 360_mil_4_8_mm
))

# ────────────────────────── 12 ──────────────────────────
_add(Caso(
    n=12,
    nome_grupo="Mu Alimentos e Bebidas S.A.",
    objetivo="Unidade \"Unitário\" (não \"Mil\") vinda do Endpoint — o valor já vem em reais absolutos, sem multiplicador.",
    roteiro="Buscar — confira que \"unidade\" vem \"Unitário\" e o valor bate direto com a faixa (15.000.000 -> 4_8_mm_20_mm) sem multiplicar por 1000.",
    matriz_analises=[r1(codigo=1100, categoria=2, valor=15_000_000, unidade_codigo="3", unidade_nome="Unitário", unidade_valor=1)],
))

# ────────────────────────── 13 ──────────────────────────
_add(Caso(
    n=13,
    nome_grupo="Nu Energia Renovável S.A.",
    objetivo="Valor extremo vindo do Endpoint — cai na faixa mais alta do catálogo (\"Acima de 10 Bi\", sem teto).",
    roteiro="Buscar — confira faixaCodigo \"acima_10_bi\" / faixaDescricao \"Acima de 10 Bi\".",
    matriz_analises=[r1(codigo=1110, categoria=2, valor=50_000_000)],  # 50 Bi
))

# ────────────────────────── 14 ──────────────────────────
_add(Caso(
    n=14,
    nome_grupo="Csi Papelaria e Escritório Ltda",
    objetivo="Valor pequeno resolvido via R2 (não R1) — cai na faixa mais baixa do catálogo (\"Até 360 Mil\").",
    roteiro="Buscar — confira faixaCodigo \"ate_360_mil\".",
    matriz_analises=[r2(codigo=1120, valor=250)],  # 250 mil -> ate_360_mil
))

# ────────────────────────── 15 ──────────────────────────
_add(Caso(
    n=15,
    nome_grupo="Ômicron Tecnologia da Informação S.A.",
    objetivo="Só matriz, ZERO no Endpoint — igual ao caso 05, mas pensado pra testar o modo \"Por faixa\" (ou \"Não possuo o faturamento\") do modal, não o \"Por valor\".",
    roteiro="Buscar (vazio) -> abrir \"Atualizar\", usar \"Por faixa\" (escolher faixa + moeda) OU \"Não possuo o faturamento\" -> salvar -> buscar de novo.",
))

# ────────────────────────── 16 ──────────────────────────
_add(Caso(
    n=16,
    nome_grupo="Pi Transportes Rodoviários S.A.",
    objetivo="Matriz + 5 subgrupos, NENHUM no Endpoint — lote maior que o caso 06, pra testar volume no fluxo de salvar.",
    roteiro="Buscar (6 linhas vazias) -> preencher e salvar todas -> buscar de novo (todas devem virar origem BASE).",
    subgrupos=[SubgrupoDef(f"Pi Filial {k}", doc_sub(16, k), []) for k in range(1, 6)],
))

# ────────────────────────── 17 ──────────────────────────
_add(Caso(
    n=17,
    nome_grupo='Rho & Sigma Participações S.A. (Grupo "Confiança")',
    objetivo="Nome do grupo com caracteres especiais (&, aspas, parênteses) — robustez de exibição/serialização.",
    roteiro="Buscar — confira que o nome aparece inteiro e corretamente escapado no JSON e na tela.",
    matriz_analises=[r2(codigo=1130, valor=7_000)],  # 7 MM -> 4_8_mm_20_mm
))

# ────────────────────────── 18 ──────────────────────────
_sub18_norte = SubgrupoDef("Tau Norte", doc_sub(18, 1), [])
_sub18_sul = SubgrupoDef("Tau Sul", doc_sub(18, 2), [r1(codigo=1140, categoria=2, valor=3_000)])  # 3 MM
_sub18_sul_dup = SubgrupoDef("Tau Sul Filial", doc_sub(18, 2), [])  # MESMO doc do "Tau Sul" -> duplicado de propósito
_add(Caso(
    n=18,
    nome_grupo="Tau Distribuidora Nacional S.A.",
    objetivo="2 entradas cruas de subgrupo no NJ6 apontam pro MESMO documento_raiz (duplicado) — testa dedup de `subgrupos_unicos`: só deve aparecer 1 linha (a do PRIMEIRO nome visto, \"Tau Sul\"), não 2, e não \"Tau Sul Filial\".",
    roteiro="Buscar — confira que só vêm 3 marcadores (matriz + Tau Norte + Tau Sul), nunca 4, e que o nome do duplicado é \"Tau Sul\" (o primeiro), com o valor do Endpoint (3 MM -> 360_mil_4_8_mm).",
    subgrupos=[_sub18_norte, _sub18_sul, _sub18_sul_dup],
))

# ────────────────────────── 19 ──────────────────────────
_add(Caso(
    n=19,
    nome_grupo="Upsilon Metalurgia S.A.",
    objetivo="A lista crua de subgrupos do NJ6 inclui um subgrupo cujo documento_raiz é IGUAL ao da matriz (cabeça do conglomerado) — testa dedup de `alvos_do_conglomerado`: a matriz não pode aparecer duplicada.",
    roteiro="Buscar — confira que vêm exatamente 2 marcadores (matriz + Upsilon Norte), NUNCA 3 — o subgrupo espelhado com o mesmo doc da matriz precisa sumir da lista.",
    matriz_analises=[r1(codigo=1150, categoria=2, valor=6_000)],  # 6 MM -> 4_8_mm_20_mm (aparece na matriz)
    nome_subgrupo_matriz="MATRIZ",  # nome DIFERENTE de propósito, pra provar que o alvo deduplicado usa o nome do conglomerado, não esse
    subgrupos=[SubgrupoDef("Upsilon Norte", doc_sub(19, 1), [r1(codigo=1151, categoria=2, valor=50)])],  # 50 mil
    dedup_extra=SubgrupoDef("Upsilon Espelho (não deve aparecer)", doc_matriz(19), []),
))

# ────────────────────────── 20 ──────────────────────────
_add(Caso(
    n=20,
    nome_grupo="Phi Varejo Digital S.A.",
    objetivo="\"Banco sempre vence\": buscar (vem do Endpoint) -> editar/salvar um valor diferente -> buscar de novo (tem que vir o valor SALVO, não mais o do Endpoint, mesmo o Endpoint continuando com o dado antigo).",
    roteiro="1) Buscar — origem ENDPOINT, 6 MM -> 4_8_mm_20_mm. 2) Salvar um valor diferente (ex.: 20 MM). 3) Buscar de novo — origem BASE, com o valor salvo, não mais o do Endpoint.",
    matriz_analises=[r1(codigo=1160, categoria=2, valor=6_000)],
))


# ═══════════════════════ montagem dos fixtures ═══════════════════════


def _pessoa(doc: str) -> dict:
    return {
        "pessoa": {
            "codigo_identificacao_pessoa": f"uuid-{doc}",
            "codigo_tipo_pessoa": "J",
            "indicador_estrangeiro": 0,
            "documento_raiz": doc,
        }
    }


def _subgrupo_raw(nome: str, doc: str, codigo_grupo_cliente_atacado: int) -> dict:
    return {
        "nome_subgrupo": nome,
        "codigo_grupo_cliente_atacado": codigo_grupo_cliente_atacado,
        "cabeca_subgrupo": {
            "codigo_identificacao_pessoa": f"uuid-{doc}",
            "codigo_tipo_pessoa": "J",
            "indicador_estrangeiro": 0,
            "documento_raiz": doc,
        },
        "participantes": [_pessoa(doc)],
    }


def montar_nj6(caso: Caso) -> dict:
    doc_m = doc_matriz(caso.n)
    subgrupos_raw = [_subgrupo_raw(caso.nome_subgrupo_matriz, doc_m, 0)]
    for i, s in enumerate(caso.subgrupos, start=1):
        subgrupos_raw.append(_subgrupo_raw(s.nome, s.doc, i))
    if caso.dedup_extra is not None:
        subgrupos_raw.append(_subgrupo_raw(caso.dedup_extra.nome, caso.dedup_extra.doc, 99))
    record = {
        "nome_grupo_economico": caso.nome_grupo,
        "codigo_tipo_grupo_economico": "E",
        "data_hora_atualizacao": "2026-07-03T10:37:28",
        "numero_funcional_atualizacao": "987350376",
        "texto_justificativa_atualizacao": "Sem Justificativa",
        "cabeca_grupo": {
            "codigo_identificacao_pessoa": f"uuid-{doc_m}",
            "codigo_tipo_pessoa": "J",
            "indicador_estrangeiro": 0,
            "documento_raiz": doc_m,
        },
        "subgrupos": subgrupos_raw,
    }
    if caso.segmento:
        record["segmento"] = caso.segmento
    return record


def montar_endpoint(caso: Caso) -> dict[str, list[dict]]:
    doc_m = doc_matriz(caso.n)
    entradas: dict[str, list[dict]] = {}
    if caso.matriz_analises:
        entradas[doc_m] = [a.to_json(doc_m) for a in caso.matriz_analises]
    for s in caso.subgrupos:
        if s.analises:
            entradas[s.doc] = [a.to_json(s.doc) for a in s.analises]
    return entradas


def main() -> None:
    nj6: dict[str, dict] = {}
    endpoint: dict[str, list[dict]] = {}

    for caso in CASOS:
        nj6[doc_matriz(caso.n)] = montar_nj6(caso)
        endpoint.update(montar_endpoint(caso))

    # caso legado (COSAN) — preservado fora da faixa "900...", testado manualmente antes
    # desses 20 casos existirem (ver docs/CASOS_TESTE_MOCK.md).
    nj6["050746577"] = {
        "nome_grupo_economico": "COSAN S A",
        "codigo_tipo_grupo_economico": "E",
        "data_hora_atualizacao": "2026-07-03T10:37:28",
        "numero_funcional_atualizacao": "987350376",
        "texto_justificativa_atualizacao": "Sem Justificativa",
        "cabeca_grupo": {
            "codigo_identificacao_pessoa": "1dd4580b-8d40-4ea7-b694-0eba343938a6",
            "codigo_tipo_pessoa": "J",
            "indicador_estrangeiro": 0,
            "documento_raiz": "050746577",
        },
        "subgrupos": [
            {
                "nome_subgrupo": "OUTROS",
                "codigo_grupo_cliente_atacado": 0,
                "cabeca_subgrupo": {
                    "codigo_identificacao_pessoa": "1dd4580b-8d40-4ea7-b694-0eba343938a6",
                    "codigo_tipo_pessoa": "J",
                    "indicador_estrangeiro": 0,
                    "documento_raiz": "050746577",
                },
                "participantes": [
                    {
                        "pessoa": {
                            "codigo_identificacao_pessoa": "1dd4580b-8d40-4ea7-b694-0eba343938a6",
                            "codigo_tipo_pessoa": "J",
                            "indicador_estrangeiro": 0,
                            "documento_raiz": "050746577",
                        }
                    }
                ],
            }
        ],
    }
    endpoint["50746577"] = [
        Analise(
            codigo=2097, categoria=1, auditado=True, original=True, valor=15_000_000,
            data_ref="2024-12-31", atualizacao="2024-06-15T14:30:00",
        ).to_json("050746577")
    ]

    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / "nj6.json").write_text(
        json.dumps(nj6, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (FIXTURES / "endpoint.json").write_text(
        json.dumps(endpoint, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"OK: {len(nj6)} conglomerados no nj6.json, {len(endpoint)} chaves no endpoint.json")

    _gerar_doc()
    print(f"OK: {DOC_OUT}")


def _gerar_doc() -> None:
    linhas: list[str] = []
    linhas.append("# Casos de teste dos mocks (NJ6 + Endpoint de Faturamento)\n")
    linhas.append(
        "Gerado por `mocks/gerar_fixtures.py` — **não edite `nj6.json`/`endpoint.json` "
        "nem esta doc na mão**; edite a lista `CASOS` no script e rode `python3 "
        "mocks/gerar_fixtures.py` de novo (regenera os três arquivos juntos, sempre "
        "consistentes entre si).\n"
    )
    linhas.append(
        "Convenção de documento: matriz do caso N = `900{N:03d}000`; subgrupo K do caso "
        "N = `900{N:03d}{K:03d}`. Ex.: caso 3, subgrupo 2 → `900003002`. O caso 0 (COSAN, "
        "doc `050746577`) é legado — mantido porque já tinha sido testado manualmente "
        "antes desses 20 existirem.\n"
    )
    linhas.append(
        "Pré-requisito: stack local no ar (`docker compose up -d --build` + uvicorn — ver "
        "`SETUP.md`). Todos os documentos abaixo respondem em "
        "`GET /irb-cra-faturamento/v1/faturamento/{documento}`; qualquer CNPJ fora desta "
        "lista agora dá **404** no NJ6 (antes desse ajuste o mock ignorava qual CNPJ era "
        "buscado e sempre devolvia o mesmo registro).\n"
    )
    linhas.append("## Índice rápido\n")
    linhas.append("| # | Documento | Grupo | Subgrupos | Objetivo |")
    linhas.append("|---|---|---|---|---|")
    for c in CASOS:
        qtd = len(c.subgrupos)
        linhas.append(
            f"| {c.n:02d} | `{doc_matriz(c.n)}` | {c.nome_grupo} | {qtd} | {c.objetivo.split(' — ')[0].split('. ')[0]} |"
        )
    linhas.append("")

    linhas.append("## Detalhe por caso\n")
    for c in CASOS:
        linhas.append(f"### Caso {c.n:02d} — {c.nome_grupo}")
        linhas.append(f"- **Documento (matriz):** `{doc_matriz(c.n)}`")
        if c.segmento:
            linhas.append(f"- **Segmento:** {c.segmento}")
        if c.subgrupos:
            subs_fmt = ", ".join(f"{s.nome} (`{s.doc}`)" for s in c.subgrupos)
            linhas.append(f"- **Subgrupos ({len(c.subgrupos)}):** {subs_fmt}")
        else:
            linhas.append("- **Subgrupos:** nenhum (só matriz)")
        # Dedupe por doc: um doc conta como "coberto" se QUALQUER entrada crua com esse
        # doc tiver análise (pode haver duplicatas de propósito, ver casos 18/19).
        docs_com_analise = {s.doc for s in c.subgrupos if s.analises}
        docs_sem_analise = {s.doc for s in c.subgrupos} - docs_com_analise
        cobertos = ([doc_matriz(c.n)] if c.matriz_analises else []) + sorted(docs_com_analise)
        faltando = sorted(docs_sem_analise)
        if cobertos:
            linhas.append(f"- **Com dado no Endpoint:** {', '.join(f'`{d}`' for d in cobertos)}")
        if faltando:
            linhas.append(f"- **SEM dado no Endpoint (MANUAL):** {', '.join(f'`{d}`' for d in faltando)}")
        linhas.append(f"- **Objetivo:** {c.objetivo}")
        linhas.append(f"- **Roteiro sugerido:** {c.roteiro}")
        linhas.append("")

    DOC_OUT.write_text("\n".join(linhas), encoding="utf-8")


if __name__ == "__main__":
    main()
