# Divergências: documento do PO × código implementado

> **Documento analisado**: "Descrição e Objetivo Projeto" — Versão 01,
> 03/06/2026, responsável Michel Franco.
> **Comparado contra**: código em `app/src/app/` e o catálogo de regras
> [`docs/REGRAS.md`](REGRAS.md).
>
> Este documento lista **só o que diverge, falta ou está ambíguo**. O que já
> está alinhado está resumido no final (§6), para dar o contraste.
>
> ⚠️ **Escopo**: boa parte do documento do PO descreve **front-end** (botões,
> telas, combos, campos desabilitados). Esses pontos estão marcados como
> `[FRONT]` e **não** são divergências deste serviço — aparecem aqui só quando
> têm consequência para o backend.

## Legenda

| Marca | Significado |
|---|---|
| 🔴 | Bloqueia implementação — precisa de resposta antes de codificar |
| 🟠 | Regra ambígua ou conflitante — dá para codificar, mas com risco de retrabalho |
| 🟡 | Documental — não muda comportamento, mas confunde quem lê |
| `[FRONT]` | Responsabilidade do front-end; listado só pelo reflexo no backend |

---

## 1. 🔴 Divergências que bloqueiam implementação

### D1 — Busca por "nome da empresa" e "ID grupo" não existe no serviço

| | |
|---|---|
| **Doc do PO** | Premissas + RN02: *"buscar CNPJs, ID grupo ou digitar o nome da empresa"*; *"A funcionalidade de busca tem que estar preparada para pesquisar ambos os cenários"* |
| **Código hoje** | `api/validacao.py` → `DOCUMENTO_PATTERN = ^\d+$` — aceita qualquer sequência de **dígitos**, sem faixa de tamanho fixa. Qualquer letra devolve **422**. `adapters/nj6.py` chama o NJ6 apenas com `?codigo_identificacao_pessoa={documento}` |
| **Impacto** | Dois dos três modos de busca prometidos **não existem**. Não é ajuste de regex: buscar por nome exige um endpoint/parâmetro do NJ6 que hoje não usamos, e "ID grupo" não está mapeado em lugar nenhum |

Nota: o NJ6 devolve um campo `codigo_grupo_cliente_atacado` nos subgrupos —
pode ser o "ID grupo", mas hoje ele é só **passthrough de saída**, nunca
entrada de busca.

### D2 — Quando o modal de confirmação deve aparecer (gate de divergência)

| | |
|---|---|
| **Doc do PO** | Premissas: *"Caso exista valor previamente carregado (histórico), exibir modal de confirmação para validação do analista"* — sugere modal **sempre que houver valor anterior** |
| **Protótipo** | O modal *"o faturamento foi alterado"* aparece inclusive com **"Valor anterior (cadastrado): -"** (vazio) — sugere modal **sempre**, mesmo sem valor anterior |
| **Código hoje** | `domain/divergencia.py` + `domain/service.py::_avaliar_gate` — só devolve **409** (pedindo confirmação) se `variação > limiteVariacaoPercentual`. Sem registro anterior, `return []` → **nunca** pede confirmação |
| **Config** | O limite vem do QuickConfig, chave `limite-Maximo-Divergencia-Porcentagem` — parâmetro que **existe e é buscado**, mas que o documento **não menciona em nenhum momento** |
| **Impacto** | Três fontes, três comportamentos diferentes. Se a regra for "sempre confirmar", o parâmetro de limite % perde a função. Se for por limite, o protótipo está errado |

### D3 — Origem do "valor previamente carregado": nossa base ou o Endpoint? ✅ Resolvido

| | |
|---|---|
| **Doc do PO** | Premissas: *"Caso exista valor previamente carregado (histórico)"* · RN04: *"Busca de histórico elegível"* aplicando R1/R2/R3 sobre spreads |
| **Resposta do PO** | **Banco sempre vence, nem precisa chamar o Endpoint.** R1/R2/R3 só valem quando a eleição é feita sobre a lista crua de análises do Endpoint (Gestão Balanço) — um registro já salvo na nossa base **nunca** é revalidado por R1/R2/R3, porque não temos como saber se foi auditado/original nem sua categoria |
| **Implementado** | `domain/service_buscar.py::_precisa_consultar_endpoint` — só consulta o Endpoint quando o subgrupo **não** tem valor salvo (e não está em quarentena). Com valor salvo, o Endpoint nem é chamado (`resolucao_marcador.py::resolver_marcador`) |

### D4 — Nível de observação: subgrupo, conglomerado, ou os dois ✅ Resolvido

| | |
|---|---|
| **Doc do PO** | Objetivo: *"priorização da unidade de observação no nível de **subgrupo**"* · RN03: *"devemos listar o cabeça do Conglomerado **e** os subgrupos"* · RN04: *"buscar no histórico **todos** os casos que fazem parte do grupo econômico"* · RN04 (final): *"Para a **aba Subgrupo**, … verificar registros de spread no nível **Conglomerado**"* |
| **Resposta do PO** | **Não vai ter paginação nem abas** — tela única, sempre lista a matriz (cabeça do conglomerado) + todos os subgrupos juntos. Um subgrupo sem spread elegível **não herda** o valor do conglomerado — **fica em branco** |
| **Implementado** | `domain/paginacao.py::alvos_do_conglomerado` — matriz + todos os subgrupos numa lista só, sem paginação/cursor. `resolucao_marcador.py` não faz nenhuma herança entre níveis: cada alvo (matriz ou subgrupo) resolve seu próprio marcador independentemente (`origem=MANUAL` quando não há banco nem Endpoint) |

---

## 2. 🟠 Divergências de regra a confirmar

### D5 — Nome da 3ª categoria da Regra 1 ✅ Resolvido

| | |
|---|---|
| **Doc do PO** | `3- Consolidado **Empresa** Específica` |
| **Código hoje** | `domain/eleicao.py` (comentário): `3 Consolidado-**Segmento** Específico` |
| **Resolução** | Confirmado: o **enum do código está correto** (`Consolidado-Segmento Específico`); o nome no documento do PO está desatualizado/errado. Nenhuma mudança de código — só resolve a dúvida de qual nome é a fonte de verdade |
| **Boa notícia** | A **ordem de prioridade bate 100%** com `PRIORIDADE_CATEGORIA_R1 = (2, 4, 3, 5, 6)` |
| **Risco (ainda vale registrar)** | O documento numera as categorias de **1 a 5** (posição na fila de prioridade), enquanto o código usa os **códigos do enum do Endpoint** (2, 4, 3, 5, 6). Quem ler o doc como "código do enum" implementa errado |

### D6 — Idade do balanço: `< 2 anos` ou `<= 24 meses` 🟠 Escopo resolvido, fronteira exata ainda aberta

| | |
|---|---|
| **Doc do PO** | *"Idade Balanço (< 2 anos)"* nas três regras |
| **Resposta do PO** | Confirmado: a idade do balanço (assim como R1/R2/R3) só se aplica à eleição sobre o Endpoint (Gestão Balanço) — nunca a um registro já salvo no nosso banco. Isso elimina a divergência interna que existia: `resolucao_marcador.py::dentro_da_janela_idade` foi **removida** (banco sempre vence, sem revalidação de idade); só resta `eleicao.py::_meses_entre`, usada exclusivamente na eleição sobre o Endpoint |
| **Ainda em aberto** | `IDADE_MAX_MESES = 24` com comparação `<=` continua elegendo um balanço com **exatamente** 24 meses. A leitura literal do doc (`< 2 anos`) sugere que não deveria. Pergunta 8 (§5) segue válida para essa fronteira específica |

### D7 — "Data Balanço": mês/ano ou data completa

| | |
|---|---|
| **Doc do PO** | RN05: *"digitar ou selecionar o **mês e ano** de referência do balanço"* |
| **Protótipo** | O campo mostra **`13/03/2024`** — data completa, com dia |
| **Código hoje** | `data_ref_balanco` é string ISO completa (`"2024-12-31"`) e é usada no **desempate por data mais recente** (`R-RES-020`), comparada lexicograficamente |
| **Impacto** | Se virar mês/ano, muda o formato persistido **e** o desempate precisa de um critério novo (dois balanços no mesmo mês empatam) |

### D8 — "Não possuo o faturamento": regra incompleta no documento

| | |
|---|---|
| **Doc do PO** | RN05 termina literalmente com: *"Ao selecionar a opção de não possuo faturamento."* — **a frase não foi concluída** |
| **Código hoje** | `R-SLV-042`: zera `valor` e `faixa_codigo` e sai **antes** de todas as validações (não valida faixa nem moeda). **Não exige justificativa** |
| **Protótipo** | A tela tem o campo *"Justifique o faturamento informado"* |
| **Impacto** | Não sabemos se justificativa é obrigatória nesse caso, o que fica gravado, nem se isso "trava" o subgrupo |

### D9 — "Faturamento líquido" — é o mesmo campo que persistimos?

| | |
|---|---|
| **Doc do PO** | RN04 e protótipo: coluna **"Faturamento líquido"** |
| **Código hoje** | Campo genérico `valor`; do Endpoint vem de `faturamento[].valor`, sem qualificação de bruto/líquido |
| **Impacto** | Se o Endpoint devolve bruto e a tela pede líquido, falta uma transformação que ninguém implementou |

### D10 — Segmentos Large / Middle / Agro

| | |
|---|---|
| **Doc do PO** | RN01: *"A funcionalidade deverá atender aos segmentos Large, Middle e Agro"* |
| **Código hoje** | `segmento` é **passthrough** do NJ6 (`R-NJ6-042`) — só é devolvido para exibição. **Nenhuma validação ou bloqueio** por segmento |
| **Impacto** | Se um analista pesquisar um documento de outro segmento (ex.: Varejo), hoje o serviço responde normalmente |

### D11 — "Responsável" é nome de pessoa; guardamos só o RACF ✅ Resolvido

| | |
|---|---|
| **Protótipo** | Coluna **"Responsável"** com nome completo ("Alice Ramos Paiva", "Carlos Alberto Silva") |
| **Resposta do PO** | O nome do responsável vem no **body** do POST de salvar (diferente do RACF, que continua vindo do header `X-RACF`) |
| **Implementado** | `InfoFaturamento.nome_responsavel` — novo campo, recebido em `FaturamentoRequest.nome_responsavel` (JSON `nomeResponsavel`), persistido junto com `racf` e devolvido em `_info_out` |

---

## 3. 🟡 Divergências documentais

### D12 — Referência a "RN06", que não existe no documento

RN04 diz: *"(Utilizando as mesmas regras citadas acima **RN06**)"*, mas o
documento vai só até **RN05**. Nosso código carrega a mesma numeração antiga:
`domain/eleicao.py` tem `"Repasse 18/06 + RN06"` e os comentários
`# RN06 R1 —` / `# RN06 R3 —`. Sugere que as regras de eleição eram **RN06** numa
versão anterior e viraram **RN04** nesta.

### D13 — "aba Subgrupo" sobrevivendo à tela única ✅ Resolvido

RN03 descreve **uma tela** com cabeça do conglomerado + subgrupos; RN04 ainda
fala em *"Para a aba Subgrupo"*. Resquício de uma versão anterior com abas.
**Confirmado pelo PO**: não vai ter paginação nem abas — tela única. O código
de abas/paginação (`R-PAG-002`, `alvos_da_aba`, `paginar`) foi **removido**;
hoje `domain/paginacao.py::alvos_do_conglomerado` sempre devolve matriz +
todos os subgrupos numa lista só.

### D14 — `[FRONT]` Itens sem reflexo no backend

Listados apenas para registrar que foram lidos e conscientemente ignorados
nesta análise: RN01 (botão na tela inicial), layout/protótipo das telas,
desabilitar o campo de faixa quando há valor (o backend já sobrescreve a faixa
pelo de/para, `R-SLV-044`), construção dos combos, e o comportamento visual do
modal.

---

## 4. O que o código faz e o documento **não** cobre

Cada item abaixo está **implementado e testado**, mas não aparece em nenhuma RN.
Ou falta no documento, ou implementamos algo que não é regra de negócio.

| Item | Onde | Situação |
|---|---|---|
| **Limite % de divergência** | QuickConfig `limite-Maximo-Divergencia-Porcentagem` | Parâmetro real, buscado pelo serviço — mas nenhuma RN o menciona (ver D2) |
| **Multiplicador de unidade** | `domain/faixa.py::_MULTIPLICADORES_UNIDADE` | `unitário=×1, mil=×1.000, milhões=×1e6, bilhões=×1e9`. A conversão antes do de/para de faixa **não está escrita em nenhuma RN** — foi definida verbalmente |
| **Remoção do zero à esquerda** | `adapters/endpoint.py::_sem_zeros_a_esquerda` | Regra técnica (o CRA guarda o documento como inteiro) passada verbalmente, não documentada |
| **Quarentena** | `quarentena`, `quarentena_desde`, `anterior` | Conceito inteiro (valor suspeito → usa o anterior) sem nenhuma menção no documento |
| **Histórico de 1 geração** | `R-DYN-030` (roll "hoje vira ontem") | Guardamos exatamente **um** valor anterior. Nenhuma RN define retenção de histórico |
| ~~Paginação~~ | ~~`LIMIT_PADRAO=10`, `LIMIT_MAXIMO=100`, cursor~~ | ✅ **Removida.** Confirmado pelo PO que não haverá paginação nem abas (D4/D13) — código de paginação foi excluído do domínio |
| **Campos passthrough** | `nomeSpread`, `arquivo`, `status`, `categoria` | Devolvidos na API; não descritos em nenhuma RN |
| **Polaridade de `indicadorFatorPonderado`** | `R-PEND-009` | ✅ **Resolvido.** Confirmado pelo PO: `indicadorFatorPonderado == True` é o balanço original. Polaridade invertida no código (`eleicao.py::_original`) |
| ~~Metadados no salvar~~ | ~~`R-PEND-012`~~ | ✅ **Moot.** `auditado/original/vigente/data_atualizacao` foram removidos do modelo — não fazem mais sentido, já que o banco nunca é revalidado por R1/R2/R3 (D3) |

---

## 5. Perguntas para o PO

### Bloqueantes — sem estas respostas não dá para implementar

1. **Busca por nome e por "ID grupo"** (D1): o NJ6 tem endpoint ou parâmetro
   para buscar por **nome da empresa**? Qual? E o que exatamente é o
   **"ID grupo"** — é o `codigoGrupoClienteAtacado` que o NJ6 devolve, ou outro
   identificador? Hoje o serviço só aceita documento numérico (qualquer
   quantidade de dígitos, sem exigir CPF/CNPJ/CGI num formato específico).

2. **Quando o modal aparece** (D2): a confirmação deve aparecer **sempre** que
   o analista informar um valor havendo (ou não) valor anterior, ou **só quando
   a variação ultrapassar** o `limite-Maximo-Divergencia-Porcentagem`
   configurado no QuickConfig? O protótipo mostra o modal até com "Valor
   anterior: -" (vazio), o que contradiz a existência do limite.

3. ~~**Contra o que comparamos**~~ (D3) ✅ **Respondido**: banco sempre vence,
   nem precisa chamar o Endpoint quando já há valor salvo. R1/R2/R3 só valem
   para a eleição sobre o Endpoint.

4. ~~**Categoria 3**~~ (D5) ✅ **Respondido**: o nome correto é *"Consolidado
   **Segmento** Específica"* (código) — o documento do PO está desatualizado.
   Ainda vale confirmar com o PO: os números **1 a 5** na RN04 são a **ordem
   de prioridade**, e não os códigos do enum do Endpoint (2, 4, 3, 5, 6)?

5. ~~**Balanço "original"**~~ (§4) ✅ **Respondido**: `indicadorFatorPonderado
   == True` é o balanço original. Código corrigido (estava invertido).

6. **"Não possuo o faturamento"** (D8): a frase da RN05 ficou incompleta. O que
   acontece ao selecionar essa opção? A **justificativa é obrigatória**? Fica
   gravado algum registro? O subgrupo pode ser reeditado depois?

### Importantes — dá para começar, mas com risco de retrabalho

7. **Data do balanço** (D7): é **mês/ano** (como diz a RN05) ou **data
   completa** (como mostra o protótipo, `13/03/2024`)? Se for mês/ano, como
   desempatar dois balanços do mesmo mês (hoje o desempate é pela data mais
   recente)?

8. **Idade do balanço** (D6) — parcialmente respondido: só vale para a eleição
   sobre o Endpoint, nunca para banco. Ainda em aberto: *"< 2 anos"* — um
   balanço com **exatamente 24 meses** é elegível ou não? E a contagem
   considera o dia (31/01 → 28/01 dá 23 ou 24 meses?)?

9. **Faturamento líquido** (D9): o valor que vem do Gestão Balanço **já é
   líquido**? O valor que o analista digita é líquido? Existe alguma
   transformação de bruto → líquido que deveríamos aplicar?

10. **Segmentos** (D10): o serviço deve **bloquear/avisar** quando o documento
    pesquisado não for Large/Middle/Agro, ou isso é apenas escopo de rollout
    (quem tem acesso à tela)?

11. ~~**Responsável**~~ (D11) ✅ **Respondido**: vem no body do POST de salvar
    (`nomeResponsavel`), não do RACF.

12. ~~**Tela única**~~ (D4/D13) ✅ **Respondido**: sem abas, sem paginação;
    subgrupo sem spread próprio elegível **fica em branco** (não herda do
    conglomerado).

13. **Unidades** (§4): confirma que a unidade **multiplica** o valor digitado —
    `100` + `"mil"` = R$ 100.000? E que a escala é `unitário ×1`, `mil ×1.000`,
    `milhões ×1.000.000`, `bilhões ×1.000.000.000`? (Implementamos assim, mas
    isso não está em nenhuma RN.)

14. **Moedas** (RN05): quais moedas entram no combo? Hoje o catálogo vem do
    QuickConfig (`catalogo-moedas`); o fallback local tem só BRL e USD, e o
    protótipo mostra USD selecionado.

### Complementares — lacunas do documento

15. **Quarentena**: existe algum conceito de valor "suspeito"/"em quarentena"
    que deva usar o valor anterior no lugar do atual? O código tem isso
    implementado, mas não veio de nenhuma RN — foi inferido.

16. **Histórico**: quantas gerações anteriores precisamos guardar? Hoje
    guardamos **uma** (o valor anterior vira "ontem" a cada gravação).

17. **Reedição**: o analista pode reeditar um faturamento já salvo? Quantas
    vezes? Existe alguma trava, aprovação ou janela de tempo?

18. ~~**Paginação**~~ ✅ **Respondido**: não vai ter paginação — a lista
    (matriz + subgrupos) sempre vem completa numa única resposta.

19. **Zero à esquerda**: confirma que a remoção do zero inicial do documento
    vale **só** para a consulta ao Gestão Balanço/CRA (que guarda como
    inteiro), e **não** para o NJ6 nem para a nossa base?

20. **Versão do documento**: esta é a **Versão 01 de 03/06/2026**. Existe
    versão mais recente? Alguns trechos (a referência a "RN06", a menção a
    "aba Subgrupo") parecem resquícios de uma versão anterior.

---

## 6. O que já está alinhado

Para contraste — estes pontos do documento **batem exatamente** com o que está
implementado e testado:

- **Cascata R1 → R2 → R3**, com a primeira regra que tiver candidato vencendo.
- **Regra 1**: auditado + original + válido, idade < 2 anos, restrita às 5
  categorias, com desempate em cascata por prioridade de categoria → data de
  atualização do spread → data do balanço. **A ordem das 5 categorias confere.**
- **Regra 2**: auditado + válido + Status Spread **Aprovado**, idade < 2 anos,
  desempate pela data do balanço mais recente.
- **Regra 3**: original + válido + Aprovado, idade < 2 anos, **excluindo
  combinados e individuais**, desempate pelo **maior faturamento**.
- **Sem histórico elegível → campos em branco** (nosso `origem=MANUAL`).
- **Faixa determinada automaticamente pelo de/para** a partir do valor
  informado, sobrescrevendo qualquer faixa enviada (`R-SLV-044`).
- **Três modalidades de input**: valor específico, faixa, "não possuo".
- **Cruzamento com o NJ6** para recuperar cabeça do conglomerado + subgrupos.
- **Campos da tela de cadastro**: moeda, unidade, valor, data do balanço e
  justificativa/racional — todos existem no contrato da API.
