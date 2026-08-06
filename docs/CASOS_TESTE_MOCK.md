# Casos de teste dos mocks (NJ6 + Endpoint de Faturamento)

Gerado por `mocks/gerar_fixtures.py` — **não edite `nj6.json`/`endpoint.json` nem esta doc na mão**; edite a lista `CASOS` no script e rode `python3 mocks/gerar_fixtures.py` de novo (regenera os três arquivos juntos, sempre consistentes entre si).

Convenção de documento: matriz do caso N = `900{N:03d}000`; subgrupo K do caso N = `900{N:03d}{K:03d}`. Ex.: caso 3, subgrupo 2 → `900003002`. O caso 0 (COSAN, doc `050746577`) é legado — mantido porque já tinha sido testado manualmente antes desses 20 existirem.

Pré-requisito: stack local no ar (`docker compose up -d --build` + uvicorn — ver `SETUP.md`). Todos os documentos abaixo respondem em `GET /irb-cra-faturamento/v1/faturamento/{documento}`; qualquer CNPJ fora desta lista agora dá **404** no NJ6 (antes desse ajuste o mock ignorava qual CNPJ era buscado e sempre devolvia o mesmo registro).

**Busca por subgrupo e busca "like" (`mocks/app/main.py`, não as fixtures)**: o mock do NJ6 resolve o mesmo endpoint de 3 formas — documento EXATO da cabeça (1 resultado), documento EXATO de um SUBGRUPO (ex. `900002001`, resolve pro conglomerado inteiro do caso 02, igual buscar pela cabeça `900002000`) e documento PARCIAL (ex. `9000` bate com os 20 casos, todos com documento começando em `900...`) — usado por `GET /irb-cra-faturamento/v1/grupos-economicos?documento=` (autocomplete). Essa lógica vive no *server* do mock (`mocks/app/main.py`), não nas fixtures geradas — não precisa rodar `gerar_fixtures.py` de novo por causa disso.

## Índice rápido

| # | Documento | Grupo | Subgrupos | Objetivo |
|---|---|---|---|---|
| 01 | `900001000` | Alfa Comércio e Distribuição S.A. | 0 | Caso mais simples: só matriz, 1 análise R1 válida |
| 02 | `900002000` | Beta Participações Ltda | 2 | Cascata completa R1/R2/R3 dentro do mesmo conglomerado |
| 03 | `900003000` | Gamma Indústria e Comércio S.A. | 8 | 8 subgrupos, sendo 4 com dado no Endpoint e 4 SEM NADA (MANUAL) |
| 04 | `900004000` | Delta Holding Multinegócios S.A. | 16 | 16 subgrupos |
| 05 | `900005000` | Épsilon Comércio Varejista Ltda | 0 | Só matriz, ZERO dado no Endpoint |
| 06 | `900006000` | Zeta Agroindustrial S.A. | 4 | Matriz + 4 subgrupos, NENHUM no Endpoint |
| 07 | `900007000` | Eta Serviços Financeiros S.A. | 1 | Subgrupo TEM análise no Endpoint, mas indicadorVigente=Inativo |
| 08 | `900008000` | Theta Engenharia e Construção S.A. | 0 | 1 análise válida em tudo (auditada/original/vigente/aprovada) mas com balanço de 2019 |
| 09 | `900009000` | Iota Mineração S.A. | 0 | 3 análises concorrendo pela R1 com categorias diferentes (6, 3, 2) |
| 10 | `900010000` | Capa Logística Integrada S.A. | 0 | 2 análises R1 na MESMA categoria |
| 11 | `900011000` | Lambda Farmacêutica S.A. | 0 | Moeda USD (não BRL) vinda do Endpoint |
| 12 | `900012000` | Mu Alimentos e Bebidas S.A. | 0 | Unidade "Real/Efetivo" (não "Mil") vinda do Endpoint |
| 13 | `900013000` | Nu Energia Renovável S.A. | 0 | Valor extremo vindo do Endpoint |
| 14 | `900014000` | Csi Papelaria e Escritório Ltda | 0 | Valor pequeno resolvido via R2 (não R1) |
| 15 | `900015000` | Ômicron Tecnologia da Informação S.A. | 0 | Só matriz, ZERO no Endpoint |
| 16 | `900016000` | Pi Transportes Rodoviários S.A. | 5 | Matriz + 5 subgrupos, NENHUM no Endpoint |
| 17 | `900017000` | Rho & Sigma Participações S.A. (Grupo "Confiança") | 0 | Nome do grupo com caracteres especiais (&, aspas, parênteses) |
| 18 | `900018000` | Tau Distribuidora Nacional S.A. | 3 | 2 entradas cruas de subgrupo no NJ6 apontam pro MESMO documento_raiz (duplicado) |
| 19 | `900019000` | Upsilon Metalurgia S.A. | 1 | A lista crua de subgrupos do NJ6 inclui um subgrupo cujo documento_raiz é IGUAL ao da matriz (cabeça do conglomerado) |
| 20 | `900020000` | Phi Varejo Digital S.A. | 0 | "Banco sempre vence": buscar (vem do Endpoint) -> editar/salvar um valor diferente -> buscar de novo (tem que vir o valor SALVO, não mais o do Endpoint, mesmo o Endpoint continuando com o dado antigo). |

## Detalhe por caso

### Caso 01 — Alfa Comércio e Distribuição S.A.
- **Documento (matriz):** `900001000`
- **Segmento:** Varejo
- **Subgrupos:** nenhum (só matriz)
- **Com dado no Endpoint:** `900001000`
- **Objetivo:** Caso mais simples: só matriz, 1 análise R1 válida. GET puro, sem precisar salvar nada antes.
- **Roteiro sugerido:** Buscar o CNPJ — o faturamento já aparece resolvido pelo Endpoint (origem ENDPOINT), faixa "5 Bi a 10 Bi".

### Caso 02 — Beta Participações Ltda
- **Documento (matriz):** `900002000`
- **Subgrupos (2):** Beta Norte (`900002001`), Beta Sul (`900002002`)
- **Com dado no Endpoint:** `900002000`, `900002001`, `900002002`
- **Objetivo:** Cascata completa R1/R2/R3 dentro do mesmo conglomerado — matriz usa R1, sub 1 usa R2, sub 2 usa R3.
- **Roteiro sugerido:** Buscar o CNPJ — confira que os 3 níveis (matriz + 2 subgrupos) resolvem por regras diferentes (dá pra ver pelo idSpread/valor de cada um, a API não expõe qual regra venceu diretamente).

### Caso 03 — Gamma Indústria e Comércio S.A.
- **Documento (matriz):** `900003000`
- **Subgrupos (8):** Gamma Norte (`900003001`), Gamma Sul (`900003002`), Gamma Leste (`900003003`), Gamma Oeste (`900003004`), Gamma Centro (`900003005`), Gamma Litoral (`900003006`), Gamma Interior (`900003007`), Gamma Fronteira (`900003008`)
- **Com dado no Endpoint:** `900003000`, `900003001`, `900003002`, `900003003`, `900003004`
- **SEM dado no Endpoint (MANUAL):** `900003005`, `900003006`, `900003007`, `900003008`
- **Objetivo:** 8 subgrupos, sendo 4 com dado no Endpoint e 4 SEM NADA (MANUAL) — mistura dentro do mesmo conglomerado.
- **Roteiro sugerido:** Buscar o CNPJ — metade das linhas já vem preenchida (ENDPOINT), a outra metade fica em branco pra você preencher manualmente e salvar.

### Caso 04 — Delta Holding Multinegócios S.A.
- **Documento (matriz):** `900004000`
- **Segmento:** Atacado
- **Subgrupos (16):** Delta Unidade 01 (`900004001`), Delta Unidade 02 (`900004002`), Delta Unidade 03 (`900004003`), Delta Unidade 04 (`900004004`), Delta Unidade 05 (`900004005`), Delta Unidade 06 (`900004006`), Delta Unidade 07 (`900004007`), Delta Unidade 08 (`900004008`), Delta Unidade 09 (`900004009`), Delta Unidade 10 (`900004010`), Delta Unidade 11 (`900004011`), Delta Unidade 12 (`900004012`), Delta Unidade 13 (`900004013`), Delta Unidade 14 (`900004014`), Delta Unidade 15 (`900004015`), Delta Unidade 16 (`900004016`)
- **Com dado no Endpoint:** `900004000`, `900004001`, `900004002`, `900004003`, `900004004`, `900004005`, `900004006`, `900004007`, `900004008`, `900004009`, `900004010`
- **SEM dado no Endpoint (MANUAL):** `900004011`, `900004012`, `900004013`, `900004014`, `900004015`, `900004016`
- **Objetivo:** 16 subgrupos — o MÁXIMO permitido no NJ6. 10 com dado no Endpoint (faixas bem espalhadas), 6 em MANUAL.
- **Roteiro sugerido:** Buscar o CNPJ — stress-test de volume/scroll da tela única (17 linhas: matriz + 16 subgrupos).

### Caso 05 — Épsilon Comércio Varejista Ltda
- **Documento (matriz):** `900005000`
- **Subgrupos:** nenhum (só matriz)
- **Objetivo:** Só matriz, ZERO dado no Endpoint — o caso mais simples de "salvar e depois buscar" (modo "Por valor").
- **Roteiro sugerido:** Buscar (vem tudo MANUAL/vazio) -> abrir "Atualizar", preencher "Por valor" -> salvar -> buscar de novo (agora vem BASE).

### Caso 06 — Zeta Agroindustrial S.A.
- **Documento (matriz):** `900006000`
- **Subgrupos (4):** Zeta Regional 1 (`900006001`), Zeta Regional 2 (`900006002`), Zeta Regional 3 (`900006003`), Zeta Regional 4 (`900006004`)
- **SEM dado no Endpoint (MANUAL):** `900006001`, `900006002`, `900006003`, `900006004`
- **Objetivo:** Matriz + 4 subgrupos, NENHUM no Endpoint — "salvar depois buscar" em lote (5 marcadores de uma vez).
- **Roteiro sugerido:** Buscar (5 linhas vazias) -> preencher e salvar cada uma (pode confirmar_divergencia se reenviar) -> buscar de novo.

### Caso 07 — Eta Serviços Financeiros S.A.
- **Documento (matriz):** `900007000`
- **Subgrupos (1):** Eta Crédito (`900007001`)
- **Com dado no Endpoint:** `900007000`, `900007001`
- **Objetivo:** Subgrupo TEM análise no Endpoint, mas indicadorVigente=Inativo — não elege em nenhuma regra (R1/R2/R3 exigem vigente), cai em MANUAL mesmo "tendo algo".
- **Roteiro sugerido:** Buscar — a matriz vem preenchida (ENDPOINT), o subgrupo fica vazio mesmo existindo uma análise pra ele (edge case: "tem mas não conta").

### Caso 08 — Theta Engenharia e Construção S.A.
- **Documento (matriz):** `900008000`
- **Subgrupos:** nenhum (só matriz)
- **Com dado no Endpoint:** `900008000`
- **Objetivo:** 1 análise válida em tudo (auditada/original/vigente/aprovada) mas com balanço de 2019 — fora da janela de 24 meses. Sem balanço vigente -> MANUAL.
- **Roteiro sugerido:** Buscar — vem vazio mesmo tendo uma análise "completa" no Endpoint (edge case de idade/vigência temporal).

### Caso 09 — Iota Mineração S.A.
- **Documento (matriz):** `900009000`
- **Subgrupos:** nenhum (só matriz)
- **Com dado no Endpoint:** `900009000`
- **Objetivo:** 3 análises concorrendo pela R1 com categorias diferentes (6, 3, 2) — testa o desempate por PRIORIDADE_CATEGORIA_R1 (categoria 2 tem que ganhar, mesmo não sendo a de maior valor).
- **Roteiro sugerido:** Buscar — confira que o valor resolvido é o da categoria 2 (100 MM -> faixa 20_mm_125_mm), não o maior valor (categoria 6, quase 1 Bi).

### Caso 10 — Capa Logística Integrada S.A.
- **Documento (matriz):** `900010000`
- **Subgrupos:** nenhum (só matriz)
- **Com dado no Endpoint:** `900010000`
- **Objetivo:** 2 análises R1 na MESMA categoria — desempate por data de atualização mais recente.
- **Roteiro sugerido:** Buscar — confira que vence a análise mais recente (atualizacao 2024-06-20), valor 9 MM -> faixa 4_8_mm_20_mm, não a de 2024-01-10.

### Caso 11 — Lambda Farmacêutica S.A.
- **Documento (matriz):** `900011000`
- **Subgrupos:** nenhum (só matriz)
- **Com dado no Endpoint:** `900011000`
- **Objetivo:** Moeda USD (não BRL) vinda do Endpoint — variabilidade de moeda.
- **Roteiro sugerido:** Buscar — confira que "moeda" vem "USD" no marcador resolvido pelo Endpoint.

### Caso 12 — Mu Alimentos e Bebidas S.A.
- **Documento (matriz):** `900012000`
- **Subgrupos:** nenhum (só matriz)
- **Com dado no Endpoint:** `900012000`
- **Objetivo:** Unidade "Real/Efetivo" (não "Mil") vinda do Endpoint — o valor já vem em reais absolutos, sem multiplicador.
- **Roteiro sugerido:** Buscar — confira que "unidade" vem "Real/Efetivo" e o valor bate direto com a faixa (15.000.000 -> 4_8_mm_20_mm) sem multiplicar por 1000.

### Caso 13 — Nu Energia Renovável S.A.
- **Documento (matriz):** `900013000`
- **Subgrupos:** nenhum (só matriz)
- **Com dado no Endpoint:** `900013000`
- **Objetivo:** Valor extremo vindo do Endpoint — cai na faixa mais alta do catálogo ("Acima de 10 Bi", sem teto).
- **Roteiro sugerido:** Buscar — confira faixaCodigo "acima_10_bi" / faixaDescricao "Acima de 10 Bi".

### Caso 14 — Csi Papelaria e Escritório Ltda
- **Documento (matriz):** `900014000`
- **Subgrupos:** nenhum (só matriz)
- **Com dado no Endpoint:** `900014000`
- **Objetivo:** Valor pequeno resolvido via R2 (não R1) — cai na faixa mais baixa do catálogo ("Até 360 Mil").
- **Roteiro sugerido:** Buscar — confira faixaCodigo "ate_360_mil".

### Caso 15 — Ômicron Tecnologia da Informação S.A.
- **Documento (matriz):** `900015000`
- **Subgrupos:** nenhum (só matriz)
- **Objetivo:** Só matriz, ZERO no Endpoint — igual ao caso 05, mas pensado pra testar o modo "Por faixa" (ou "Não possuo o faturamento") do modal, não o "Por valor".
- **Roteiro sugerido:** Buscar (vazio) -> abrir "Atualizar", usar "Por faixa" (escolher faixa + moeda) OU "Não possuo o faturamento" -> salvar -> buscar de novo.

### Caso 16 — Pi Transportes Rodoviários S.A.
- **Documento (matriz):** `900016000`
- **Subgrupos (5):** Pi Filial 1 (`900016001`), Pi Filial 2 (`900016002`), Pi Filial 3 (`900016003`), Pi Filial 4 (`900016004`), Pi Filial 5 (`900016005`)
- **SEM dado no Endpoint (MANUAL):** `900016001`, `900016002`, `900016003`, `900016004`, `900016005`
- **Objetivo:** Matriz + 5 subgrupos, NENHUM no Endpoint — lote maior que o caso 06, pra testar volume no fluxo de salvar.
- **Roteiro sugerido:** Buscar (6 linhas vazias) -> preencher e salvar todas -> buscar de novo (todas devem virar origem BASE).

### Caso 17 — Rho & Sigma Participações S.A. (Grupo "Confiança")
- **Documento (matriz):** `900017000`
- **Subgrupos:** nenhum (só matriz)
- **Com dado no Endpoint:** `900017000`
- **Objetivo:** Nome do grupo com caracteres especiais (&, aspas, parênteses) — robustez de exibição/serialização.
- **Roteiro sugerido:** Buscar — confira que o nome aparece inteiro e corretamente escapado no JSON e na tela.

### Caso 18 — Tau Distribuidora Nacional S.A.
- **Documento (matriz):** `900018000`
- **Subgrupos (3):** Tau Norte (`900018001`), Tau Sul (`900018002`), Tau Sul Filial (`900018002`)
- **Com dado no Endpoint:** `900018002`
- **SEM dado no Endpoint (MANUAL):** `900018001`
- **Objetivo:** 2 entradas cruas de subgrupo no NJ6 apontam pro MESMO documento_raiz (duplicado) — testa dedup de `subgrupos_unicos`: só deve aparecer 1 linha (a do PRIMEIRO nome visto, "Tau Sul"), não 2, e não "Tau Sul Filial".
- **Roteiro sugerido:** Buscar — confira que só vêm 3 marcadores (matriz + Tau Norte + Tau Sul), nunca 4, e que o nome do duplicado é "Tau Sul" (o primeiro), com o valor do Endpoint (3 MM -> 360_mil_4_8_mm).

### Caso 19 — Upsilon Metalurgia S.A.
- **Documento (matriz):** `900019000`
- **Subgrupos (1):** Upsilon Norte (`900019001`)
- **Com dado no Endpoint:** `900019000`, `900019001`
- **Objetivo:** A lista crua de subgrupos do NJ6 inclui um subgrupo cujo documento_raiz é IGUAL ao da matriz (cabeça do conglomerado) — testa dedup de `alvos_do_conglomerado`: a matriz não pode aparecer duplicada.
- **Roteiro sugerido:** Buscar — confira que vêm exatamente 2 marcadores (matriz + Upsilon Norte), NUNCA 3 — o subgrupo espelhado com o mesmo doc da matriz precisa sumir da lista.

### Caso 20 — Phi Varejo Digital S.A.
- **Documento (matriz):** `900020000`
- **Subgrupos:** nenhum (só matriz)
- **Com dado no Endpoint:** `900020000`
- **Objetivo:** "Banco sempre vence": buscar (vem do Endpoint) -> editar/salvar um valor diferente -> buscar de novo (tem que vir o valor SALVO, não mais o do Endpoint, mesmo o Endpoint continuando com o dado antigo).
- **Roteiro sugerido:** 1) Buscar — origem ENDPOINT, 6 MM -> 4_8_mm_20_mm. 2) Salvar um valor diferente (ex.: 20 MM). 3) Buscar de novo — origem BASE, com o valor salvo, não mais o do Endpoint.
