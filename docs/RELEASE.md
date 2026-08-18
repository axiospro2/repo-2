# Release — Faturamento IRB/CV4 (`irb-cra-faturamento` + BFF)

## Tipo de Alteração

- [x] Nova funcionalidade
- [ ] Bug
- [ ] Refatoração

> **Primeira release do serviço** — nada disso está em nenhum ambiente ainda. Não há versão anterior
> para comparar: é a entrega inicial completa dos dois fluxos de faturamento (SALVAR e BUSCAR) da
> tela do CRA, com o BFF que o front consome.

---

## O que é o projeto

**Resumo:** 144 arquivos — ~3,2 mil linhas de código de produção da Lambda (`app/src/`), ~1,1 mil do
BFF (`exemplo/src/`), ~4 mil de testes (unitários + BDD), ~5,2 mil de mocks / scripts / TAAC e ~7,6
mil de documentação (`docs/`).

**Contexto:** a Lambda de **Faturamento IRB/CV4** serve a tela de faturamento do CRA, dentro do
domínio de conglomerados e subgrupos econômicos. Ela existe para responder uma pergunta por
subgrupo: *qual é o faturamento vigente deste subgrupo?* — buscando o melhor valor disponível
automaticamente e deixando o analista corrigir quando o automático não serve.

São dois caminhos numa mesma Lambda:

- **BUSCAR** (leitura, *read-through*) — o NJ6 resolve o conglomerado e seus subgrupos a partir de um
  documento; para cada subgrupo sem valor salvo, o Endpoint de Gestão de Balanço é consultado em
  paralelo e a cascata **R1 → R2 → R3** elege um único balanço; o que já está na nossa base sempre
  vence. Antes disso há um passo de autocomplete (`/grupos-economicos`), que faz busca "like" no NJ6
  por documento parcial.
- **SALVAR** (escrita) — o analista informa valor + moeda + unidade (ou só a faixa, ou "não possuo o
  faturamento"); o serviço valida contra o catálogo do QuickConfig, converte a unidade para reais,
  classifica a faixa, roda o **gate de divergência** contra o que já estava salvo e persiste no
  DynamoDB, carimbando o RACF de quem informou.

Em volta disso: FastAPI + Mangum sobre API Gateway, arquitetura hexagonal (`api → domain → adapters
→ core`), autenticação M2M OAuth2 nas chamadas externas, logging estruturado para o Datadog com
CPF/CNPJ mascarado, 290 testes unitários com 99% de cobertura, BDD com behave, TAAC HTTP real,
stack local de mocks via `docker-compose` e as regras de negócio documentadas em `docs/`.

### Aplicação / Entry-point

**Arquivos principais:** `app/src/app/main.py` (Lambda interna), `exemplo/src/app/main.py` +
`exemplo/lambda_function.py` (BFF)

- **Tipo de aplicação:** FastAPI (`title="Faturamento"`, `version="1.0.0"`), arquitetura hexagonal
  `api → domain → adapters → core` — o domínio não depende de framework nem de I/O, só de
  `Protocol`s.
- **Handler:** AWS Lambda via `Mangum` — `handler = Mangum(app)` em `app.main` (evento API Gateway
  proxy → ASGI). O BFF expõe o seu próprio handler em `exemplo/lambda_function.py`.
- **Endpoints básicos:** `GET /health` → `{"status": "ok"}` (fora do schema OpenAPI).
- **Middlewares relevantes:**
  - `_contexto_invocacao` (`main.py:32`) — limpa e vincula o contexto de log por requisição
    (`request_id` vindo de `aws.context.aws_request_id`, método, path), loga
    `faturamento.requisicao.inicio` / `.fim` com `latencia_ms` e `status_code`, e re-levanta
    exceções depois de logar `faturamento.requisicao.erro_middleware`.
  - Logging estruturado JSON (`core/logging.py`) para o Datadog, com **mascaramento de CPF/CNPJ**
    (`core/mascaramento.py` — só os 4 últimos dígitos).
  - Handlers de exceção registrados em `api/errors.py` (domínio → HTTP, num lugar só).
  - No BFF: `CORSMiddleware` (métodos `GET/POST/OPTIONS`, headers `Authorization`/`Content-Type`).

### Rotas / Endpoints

API interna — prefixo `/irb-cra-faturamento/v1`:

| Verbo | Rota | Descrição |
| --- | --- | --- |
| `POST` | `/faturamento/{documento}` | **SALVAR** — valida faixa/moeda/unidade, roda o gate de divergência contra o valor já salvo e persiste no DynamoDB. `201` no sucesso, `409` se houver divergência não confirmada. Header `X-RACF` identifica quem informou. |
| `GET` | `/faturamento/{documento}` | **BUSCAR** — *read-through*: NJ6 resolve o conglomerado, o Endpoint é consultado em paralelo só para os alvos sem valor salvo, e a cascata R1/R2/R3 elege o melhor balanço. Devolve matriz + todos os subgrupos numa lista só. |
| `GET` | `/grupos-economicos?documento=` | **Autocomplete** — busca "like" no NJ6 por documento parcial; devolve os grupos econômicos candidatos (cabeça + subgrupos, sem faturamento). |
| `GET` | `/health` | Health check (sem prefixo, fora do OpenAPI). |

BFF (`exemplo/`) — prefixo `/api-irb-cra-faturamento-bff/v1`:

| Verbo | Rota | Descrição |
| --- | --- | --- |
| `POST` | `/faturamento/{documento}` | Forward do SALVAR para a API interna. |
| `GET` | `/faturamento/{documento}` | Forward do BUSCAR. |
| `GET` | `/grupos-economicos` | Forward do autocomplete (repassa a querystring inteira). |
| `GET` | `/conglomerados/{documento}/subgrupos` | Forward de subgrupos — ⚠ **a rota correspondente não existe na API interna** (ver "Impacto"). |
| `GET` | `/catalogo` | Não faz forward: consome o QuickConfig direto e devolve faixas/moedas para os dropdowns do front. |

O OpenAPI gerado está em `app/api.yaml`.

### Regras de Negócio

**Validação (SALVAR — `domain/service.py`, `api/validacao.py`)**

- `documento` (path/query): só dígitos (`^\d+$`), sem faixa fixa de tamanho e sem validar dígito
  verificador — CPF, CNPJ, CGI ou outro identificador numérico.
- Lista de `marcadores` não pode ser vazia → `422 "Nenhum marcador informado para classificar."`
- `subgrupoDoc` obrigatório em cada marcador → `422`.
- `atual.moeda` obrigatória e presente no catálogo do QuickConfig (fallback `BRL`/`USD`).
- `atual.valor` **ou** `atual.faixaCodigo` — um dos dois; nenhum → `422 FaixaObrigatoria`.
- `semFaturamento: true` ("não possuo o faturamento") zera valor + faixa e **pula** todas as
  validações de valor/faixa/unidade/moeda.
- O Pydantic do request é propositalmente permissivo (tudo `Optional`, `extra="ignore"`,
  `alias_generator=to_camel`): quem valida shape *e* negócio é o domínio, num lugar só — por isso
  os 422 vêm com mensagem em português, não com `loc`/`msg` do FastAPI.

**Cálculo e escala de unidade (`domain/faixa.py`)**

- De-para automático valor → faixa: os limiares `min`/`max` das faixas estão em **reais absolutos**,
  intervalo `[min, max)`, `max: null` = sem teto. Havendo `valor`, o `faixaCodigo` enviado é
  ignorado e a faixa é recalculada.
- `unidade` é uma **escala linear base 10** com duas origens de vocabulário, ambas mapeadas:
  - **SALVAR manual** (combo da tela): `unitário` ×1, `mil` ×1.000, `milhões` ×1.000.000,
    `bilhões` ×1.000.000.000 — com e sem acento.
  - **Endpoint automático** (enum Java `UnidadeEnum`): `Real/Efetivo` ×1, `Mil`, `Milhões`,
    `Bilhões`. `"Real/Efetivo"` é string diferente de `"unitário"`, por isso as duas tabelas
    precisam existir.
  - Default quando omitida: `"milhoes"`. Unidade desconhecida → `422`.

**Gate de divergência (`domain/divergencia.py`)**

Roda no SALVAR **antes** de gravar, comparando cada marcador com o que já está salvo para aquele
par (conglomerado, subgrupo). Sem registro salvo, nunca dispara. Divergência → `409
ConfirmacaoNecessaria` com a lista de divergências; a tela reenvia o marcador com
`confirmadoDivergencia: true` para gravar mesmo assim.

| Tipo | Condição |
| --- | --- |
| `VALOR` | Variação percentual acima do limite (`limite-Maximo-Divergencia-Porcentagem`; fallback 30%). |
| `MOEDA` | Moeda salva ≠ moeda nova. |
| `UNIDADE` | Unidade diferente **pelo multiplicador** — `"milhoes"` vs `"milhões"` não divergem. |

**Eleição do melhor balanço — R1/R2/R3 (`domain/eleicao.py`, repasse 18/06 + RN06)**

Regra nossa, não do Endpoint: ele devolve as análises cruas paginadas e estas regras escolhem
**1 valor**, em cascata (a primeira regra com candidato ganha):

- **R1** — auditado + original + vigente, idade < 24 meses, só nas 5 categorias de
  `PRIORIDADE_CATEGORIA_R1` (2, 4, 3, 5, 6). Desempate: prioridade de categoria → data de
  atualização mais recente → data de balanço mais recente.
- **R2** — auditado + vigente + Aprovado (`situacao.codigo == 3`), idade < 24 meses. Desempate:
  data de balanço mais recente.
- **R3** — original + vigente + Aprovado, idade < 24 meses, excluindo combinados e individuais
  (`CATEGORIAS_R3_EXCLUIDAS` = 1, 6, 7, 8, 9). Desempate: **maior** valor.

O multiplicador de unidade **não** é aplicado aqui — `valor_faturamento` sai cru e a escala para
reais só entra na classificação de faixa (`domain/resolucao_marcador.py`).

**Seleção e composição de dados (BUSCAR — `domain/service_buscar.py`, `paginacao.py`, `resolucao_marcador.py`)**

- Tela única, **sem abas e sem paginação** (confirmado com o PO): `alvos_do_conglomerado` devolve a
  matriz + todos os subgrupos numa lista só, sem duplicar o documento da matriz caso ele também
  apareça na lista crua de subgrupos do NJ6.
- Precedência por subgrupo, nesta ordem: **quarentena → banco → Endpoint → MANUAL**.
  1. Subgrupo em **quarentena** com um `anterior` não vazio: o valor anterior é eleito como vigente
     (`em_quarentena = true`) e o Endpoint nem é consultado.
  2. **Valor salvo no banco (`BASE`) sempre vence**, sem revalidação e sem checagem de idade —
     R1/R2/R3 só se aplicam às análises cruas do Endpoint, nunca a um registro nosso (não há como
     saber se um valor digitado foi "auditado"). Por isso o Endpoint só é consultado (em
     `ThreadPoolExecutor`, em paralelo) para os alvos **sem** nada salvo.
  3. Sem banco e sem Endpoint → o marcador cai em `MANUAL` (a tela pede o preenchimento).
- Falha isolada do Endpoint em um subgrupo não derruba os demais: aquele alvo vira `MANUAL` e o
  resto do conglomerado é devolvido normalmente.

**Persistência (`adapters/repository.py`)**

- Tabela `tbcv4163_fatm_cogl_subg`: `cod_cogl` (HASH) + `cod_subg` (RANGE), um item por
  (conglomerado, subgrupo), sem GSI e sem snapshots `SPREAD#`.
- `save()` é **upsert incremental**: grava/atualiza só os marcadores presentes no payload e faz o
  roll "hoje vira ontem"; nunca apaga um subgrupo por ele estar ausente do payload — o analista
  preenche a carteira aos poucos.
- Ao gravar, `origem` vira sempre `BASE` e o `nivel` é derivado (matriz = marcador cujo
  `subgrupoDoc == conglomeradoDoc`).

**Normalização / tratamento de documentos**

- `mascarar_documento` (`core/mascaramento.py`): CPF/CNPJ/CGI nunca vão em texto puro para o
  Datadog — só os 4 últimos dígitos; documentos com ≤ 4 caracteres são mascarados por inteiro.
- O NJ6 casa documento parcial "como um LIKE" no autocomplete e resolve tanto o documento da cabeça
  quanto o de um subgrupo para o mesmo conglomerado.

### Infraestrutura

- **Arquivos Terraform / IaC: não existem neste repositório** (sem `.tf`, `template.yaml`,
  `serverless.yml` ou CDK). O `docker-compose.yml` da raiz é **apenas o stack de mocks local**, não
  infraestrutura real. O que segue está documentado como **inferência** em `docs/ARQUITETURA.md` §6:
  - API Gateway na frente da Lambda (o handler é `Mangum`, feito para eventos de proxy).
  - AWS Lambda com runtime Python (CodeBuild usa 3.13; o código tem `target-version = py311`).
  - Terraform provisionando e injetando `AUTH_CLIENT_ID`/`AUTH_CLIENT_SECRET` a partir do **Secrets
    Manager**.
  - **Lambda Layer** com CA bundle customizado em `/opt/ca_bundle.crt` ou `/opt/certs/ca_bundle.crt`
    (`core/ssl_context.py`, compartilhado por `nj6.py` e `endpoint.py`).
  - Extensão/forwarder do Datadog coletando os logs JSON do stdout.
- **IAM necessário:** `dynamodb:GetItem` / `Query` / `PutItem` / `UpdateItem` na tabela
  `tbcv4163_fatm_cogl_subg`; `secretsmanager:GetSecretValue` nos secrets de credenciais M2M;
  `logs:*` padrão da Lambda. **A validar** — não há política versionada no repo.
- **Secrets / Parameters:** `AUTH_CLIENT_ID` + `AUTH_CLIENT_SECRET` (client_credentials M2M),
  `ITAU_API_KEY`; o TAAC lê `CLIENT_ID`/`CLIENT_SECRET` do Secrets Manager via ARN em
  `tests/testspec-dev.yml` (hoje com ARN e URL de placeholder — **TODO no arquivo**).
- **Serviço de parâmetros:** QuickConfig, biblioteca interna `manager` (cluster próprio, **não é
  REST**) — configurado por `QUICKCONFIG_CLUSTER_MEMBERS`. Sem cluster disponível, o adapter cai num
  fallback hardcoded (6 faixas, BRL/USD, 30% de limite). Localmente é preciso pôr `dev-stubs/` no
  `PYTHONPATH`, porque `adapters/parametros.py` importa `manager` no topo do arquivo.
- **Variáveis de ambiente** (`core/settings.py`): `TABELA_FATURAMENTO`, `RACF_HEADER`,
  `NJ6_BASE_URL`, `ENDPOINT_BASE_URL`, `INTEG_TIMEOUT_S`, `PARAMETROS_RETRIES`,
  `QUICKCONFIG_CLUSTER_MEMBERS`, `QUICKCONFIG_APP_NAME`, `QUICKCONFIG_TTL_S`,
  `QUICKCONFIG_KEY_FAIXAS`, `QUICKCONFIG_KEY_MOEDAS`, `QUICKCONFIG_KEY_AUDITORIAS`,
  `QUICKCONFIG_KEY_LIMITE_DIVERGENCIA`, `TOKEN_URL`, `TOKEN_TTL_MARGEM_S`, `TOKEN_TIMEOUT_S`,
  `AUTH_CLIENT_ID`, `AUTH_CLIENT_SECRET`, `ITAU_API_KEY`, `ITAU_CORRELATION_ID`, `ITAU_FLOW_ID`.

### Testes

- **Unitários (pytest):** `app/tests/unit/` — 25 arquivos de teste cobrindo domínio, adapters, API e
  core.
- **Aceite / BDD (behave, Gherkin):** `app/features/*.feature` + `app/features/steps/` — chamam o
  domínio direto, com fakes em memória, sem HTTP.
- **TAAC (pytest + httpx, HTTP real):** `tests/acceptance/` — requisições reais contra a API de um
  ambiente; trava a execução se `AMBIENTE` for produção (`pytest_configure` em
  `tests/acceptance/conftest.py`).
- **Fakes/fixtures para integrações externas:** `app/tests/http_fakes.py` (rede),
  `app/tests/dynamo_fakes.py` (banco), `app/tests/fakes.py`, `app/src/app/adapters/fixtures/`.
- **Stack de mocks local:** `mocks/` + `docker-compose.yml` — DynamoDB Local (porta 8010),
  criação da tabela e `mock-api` (porta 8080) servindo NJ6, Endpoint e `POST /oauth/token`.

### Documentação e Qualidade

- **Documentos:** [`README.md`](../README.md), [`SETUP.md`](../SETUP.md),
  [`RECONSTRUCAO.md`](../RECONSTRUCAO.md), `docs/ARQUITETURA.md`, `docs/FLUXOS.md`,
  `docs/REGRAS.md` (5.270 linhas — catálogo completo das regras), `docs/POST_SALVAR.md`,
  `docs/PARAMETROS.md`, `docs/DIVERGENCIAS_PO.md`, `docs/CASOS_TESTE_MOCK.md`,
  `docs/CANDIDATOS_PARAMETRIZACAO.md`, `docs/AVALIACAO.md`.
- **Qualidade:** `app/pyproject.toml` — `black` (line-length 100, `preview = true`) e `ruff`
  (`E`, `F`, `I`, `W`; `E501` ignorado, isort com `known-first-party = ["app"]`).
- **Pipeline / hooks:** `tests/testspec-dev.yml` (CodeBuild: Python 3.13, unitários no `pre_build`,
  TAAC no `build`, relatórios JUnit XML), `.pre-commit-config.yaml` (black + ruff `--fix`) e
  `scripts/checar_docs_atualizados.py` — hook que **bloqueia o commit** se `app/src/app/**/*.py`
  mudou sem nenhum `.md` junto.
- **Scripts de apoio:** `scripts/curls_exemplos.sh`, `scripts/curls_salvar_post.sh` (um subcomando
  por cenário do `docs/POST_SALVAR.md`).

---

## Por que este serviço existe

- **Situação atual:** não existe backend para a tela de faturamento do CRA. O serviço é novo e ainda
  **não foi para nenhum ambiente** — esta release é o pedido de subida inicial (dev primeiro).
- **Objetivo:** entregar o MVP dos dois fluxos (SALVAR e BUSCAR) com as regras de negócio
  implementadas, testadas e documentadas, e o BFF que o front consome.
- **Necessidade de negócio:** o analista precisa ver, numa tela única (sem abas e sem paginação —
  confirmado com o PO), a matriz e todos os subgrupos do conglomerado com o faturamento **já eleito
  automaticamente** pelas regras R1/R2/R3 sobre as análises do Endpoint, e poder corrigir manualmente
  o que estiver errado — com um gate que exige confirmação explícita quando o valor novo diverge
  demais do que já estava salvo. Hoje esse trabalho é manual e sem trilha de quem informou o quê.
- **Segurança / compliance / arquitetura que moldaram o desenho:**
  - **LGPD** — CPF/CNPJ/CGI nunca vão em texto puro para o Datadog: `core/mascaramento.py` deixa só
    os 4 últimos dígitos, o suficiente para correlacionar log com chamado.
  - **Auth M2M** — todas as chamadas externas usam OAuth2 `client_credentials`, com cache de token e
    margem de TTL; credenciais vêm do Secrets Manager via Terraform, nunca do código.
  - **TLS corporativo** — CA bundle do Itaú carregado da Lambda Layer (`core/ssl_context.py`),
    compartilhado por NJ6 e Endpoint.
  - **Arquitetura hexagonal** — o domínio não depende de `boto3`, FastAPI nem de biblioteca HTTP; o
    fluxo BUSCAR é dividido em `service_buscar.py` (orquestração) + `paginacao.py` (seleção de alvos)
    + `resolucao_marcador.py` (qual valor vence), com uma única fonte de verdade para a cascata
    R1/R2/R3.
  - **Rastreabilidade** — o `X-RACF` de quem informou é persistido junto com o valor e volta no GET.
  - **Resiliência** — falha isolada do Endpoint em um subgrupo não derruba a resposta do
    conglomerado; retry com `tenacity` nas integrações HTTP.

---

## Há impacto em outros serviços/sistemas?

Como é a primeira subida, não há sistema sofrendo *mudança* de comportamento — o impacto é de
**novas dependências e novo consumo**. Nada aqui exige alteração nos serviços de terceiros, mas
todos precisam estar liberados/provisionados no ambiente antes do deploy.

| Sistema | Impacto |
| --- | --- |
| **Front / tela do CRA** | Passa a ter backend. Consome os endpoints via BFF, no fluxo: autocomplete (`/grupos-economicos`, documento parcial) → escolha do documento exato → `GET /faturamento/{documento}` → `POST` para salvar. Tela única, sem abas e sem paginação. |
| **BFF (`exemplo/`)** | Sobe junto. Repassa body, status e resposta sem alterar. Duas diferenças que afetam quem chama: `min_length=11` no path (documentos de 9 dígitos são rejeitados com 422 **antes** do forward) e os headers do caller **não** são repassados — o BFF injeta `x-itau-apikey`, `x-itau-correlationid` (UUID4 novo) e o `Authorization` do token que ele mesmo obtém; do caller, só o `X-RACF` segue adiante. |
| **NJ6 (grupos econômicos)** | Novo consumidor, em dois modos: documento exato (cabeça ou subgrupo) e busca "like" do autocomplete. Precisa de liberação de rede e de client M2M autorizado no ambiente. |
| **Endpoint / Gestão de Balanço (`spreads-faturamento`)** | Novo consumidor. Chamado **em paralelo** no BUSCAR, só para os alvos sem valor salvo — o volume tende a cair conforme a base é preenchida. Vale alinhar volume esperado com o time (Deus/Felipe). |
| **QuickConfig (lib `manager`)** | Nova dependência de cluster para faixas, moedas e limite de divergência (cache TTL 300s). **Atenção:** sem `QUICKCONFIG_CLUSTER_MEMBERS` configurado o adapter cai num fallback hardcoded — o serviço sobe, mas com catálogo errado, sem falhar visivelmente. |
| **DynamoDB — `tbcv4163_fatm_cogl_subg`** | Tabela nova a ser criada (`cod_cogl` HASH / `cod_subg` RANGE, sem GSI). Escrita incremental por upsert. |
| **Datadog** | Nova origem de logs JSON estruturados (`faturamento.requisicao.*`, `faturamento.divergencia_barrada`, `faturamento.persistido`) com `request_id` para correlação; documentos mascarados. |
| **STS / provedor de token** | Novo consumidor M2M (`client_credentials`) — precisa de client cadastrado por ambiente. |

⚠ **Divergência conhecida (não resolvida nesta release):** o BFF expõe
`GET /conglomerados/{documento}/subgrupos` e faz forward para o mesmo path na API interna, **que não
tem essa rota** (`api/routes_buscar.py` só registra `/faturamento/{documento}` e
`/grupos-economicos`). Na prática essa rota do BFF responde o 404 da API interna.
`docs/ARQUITETURA.md` §2 também ainda lista essa rota como se existisse na API interna. Decidir se a
rota é removida do BFF ou implementada na API interna antes de expor o BFF ao front.

---

## Como testar

### Pré-requisitos

- Python 3.11+ (CodeBuild roda 3.13; `black`/`ruff` com `target-version = py311`).
- Docker + Docker Compose (stack de mocks).
- `PYTHONPATH=app/src:dev-stubs` — o `dev-stubs/manager/` é obrigatório localmente, senão o import
  de `adapters/parametros.py` quebra o boot.
- Variáveis de ambiente (`cp .env.example .env` já traz os defaults apontando para os mocks):
  - `AWS_ENDPOINT_URL_DYNAMODB=http://localhost:8010`, `AWS_ACCESS_KEY_ID=local`,
    `AWS_SECRET_ACCESS_KEY=local`, `AWS_DEFAULT_REGION=us-east-1`
  - `TABELA_FATURAMENTO=tbcv4163_fatm_cogl_subg`
  - `NJ6_BASE_URL=http://localhost:8080`, `ENDPOINT_BASE_URL=http://localhost:8080`,
    `INTEG_TIMEOUT_S=5`
  - `TOKEN_URL=http://localhost:8080/oauth/token`, `AUTH_CLIENT_ID`, `AUTH_CLIENT_SECRET`
  - `ITAU_API_KEY` (+ `ITAU_CORRELATION_ID`, `ITAU_FLOW_ID` quando aplicável)
  - Em DEV/HML: `QUICKCONFIG_CLUSTER_MEMBERS` (sem ele, o catálogo é o fallback hardcoded)
  - TAAC: `AMBIENTE`, `BASE_URL`, `CLIENT_ID`, `CLIENT_SECRET`, `DOCUMENTO_TESTE`, `RACF_TESTE`

### Requests (passo a passo)

Collection executável: [`scripts/curls_salvar_post.sh`](../scripts/curls_salvar_post.sh) (um
subcomando por cenário; `todos` roda a lista inteira) e
[`scripts/curls_exemplos.sh`](../scripts/curls_exemplos.sh). O OpenAPI para importar em
Postman/Insomnia está em [`app/api.yaml`](../app/api.yaml). Contrato detalhado do POST em
[`docs/POST_SALVAR.md`](POST_SALVAR.md); documentos de teste (`900001000`…`900020000`) em
[`docs/CASOS_TESTE_MOCK.md`](CASOS_TESTE_MOCK.md).

```bash
# 1. subir mocks (DynamoDB local + tabela + NJ6/Endpoint/STS fake)
docker compose up -d --build
curl http://localhost:8080/health

# 2. subir a aplicação
cp .env.example .env
export $(cat .env | xargs)
export PYTHONPATH=app/src:dev-stubs
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 3. health
curl http://localhost:8000/health

# 4. autocomplete (documento parcial, busca "like" no NJ6)
curl "http://localhost:8000/irb-cra-faturamento/v1/grupos-economicos?documento=9000"

# 5. BUSCAR (documento exato) — token → NJ6 → Endpoint → R1/R2/R3 → DynamoDB
curl http://localhost:8000/irb-cra-faturamento/v1/faturamento/050746577

# 6. SALVAR (menor body que grava)
curl -sS -X POST "http://localhost:8000/irb-cra-faturamento/v1/faturamento/900001000" \
  -H "Content-Type: application/json" \
  -H "X-RACF: A123456" \
  -d '{
    "conglomeradoDoc": "900001000",
    "marcadores": [
      {"subgrupoDoc": "900001000",
       "atual": {"valor": "5000000", "moeda": "BRL", "unidade": "unitario"}}
    ]
  }'
```

### Cenários de testes

Baseados em `app/features/*.feature` + `app/features/steps/`, em `tests/acceptance/` (TAAC) e nos
subcomandos de `scripts/curls_salvar_post.sh`:

**Fluxo SALVAR — `app/features/salvar_faturamento.feature` (5 cenários)**

- Valor dentro de faixa conhecida (`5000000` BRL) → persistido, faixa `FAIXA_2` calculada pelo
  de-para.
- Faturamento sem nenhum marcador → rejeitado com erro de validação.
- Valor fora de qualquer faixa conhecida (`1`, com as faixas do fixture) → erro de validação.
- Divergência de valor não confirmada (salvo `1000000` → novo `5000000`, limite 30%) → exige
  confirmação.
- A mesma divergência com o marcador confirmando → persistido com sucesso.

**Fluxo BUSCAR — `app/features/buscar_faturamento.feature` (5 cenários)**

- Subgrupo sem valor salvo e com resultado no Endpoint → origem `ENDPOINT`.
- Subgrupo sem banco e sem Endpoint → origem `MANUAL`.
- Subgrupo em quarentena com valor anterior salvo → usa o anterior (`4000000`), sem consultar o
  Endpoint.
- Banco (`6000000`) vs Endpoint (`9000000`) → banco vence, origem `BASE`.
- Falha isolada do Endpoint em um subgrupo → aquele vira `MANUAL`, o outro continua `ENDPOINT`.

**Cenários adicionais do POST via `scripts/curls_salvar_post.sh`** (HTTP real, cobrem o que o BDD de
domínio não cobre): `minimo`, `completo`, `por-faixa`, `sem-faturamento`, `unidade-omitida` (201);
`divergencia` (409, variação 400%) e `divergencia-confirmada` (201); e os 422 —
`erro-sem-marcadores`, `erro-sem-subgrupo-doc`, `erro-sem-valor-nem-faixa`, `erro-sem-moeda`,
`erro-moeda-invalida`, `erro-unidade-desconhecida`, `erro-valor-fora-das-faixas`,
`erro-documento-invalido`.

**Autocomplete** — `GET /grupos-economicos?documento=9000` deve devolver os 20 grupos de
`docs/CASOS_TESTE_MOCK.md`; buscar pelo documento de um **subgrupo** (`900002001`) resolve o mesmo
conglomerado que buscar pela cabeça (`900002000`).

---

## Checklist

- [x] Testes unitários passando — `app/tests/unit/`: **290 passed**, 99% de cobertura de linha
      (1176 statements, 9 sem cobertura)
- [x] Testes de aceite (BDD) passando — `app/features/`: **2 features, 10 cenários, 64 steps**, 0
      falhas
- [ ] TAAC (`tests/acceptance/`) executado contra DEV — **só é possível depois da primeira subida**;
      `tests/testspec-dev.yml` ainda tem `BASE_URL` e ARNs de Secrets Manager de placeholder (`TODO`
      no arquivo)
- [x] Lint e formatação OK — `ruff check` limpo, `black --check`: 69 arquivos inalterados
- [x] `README.md` e documentação (`docs/`) escritos
- [ ] Variáveis de ambiente e secrets provisionados em dev/hom/prod — **pendente**:
      `AUTH_CLIENT_ID`/`AUTH_CLIENT_SECRET` (Secrets Manager) e `QUICKCONFIG_CLUSTER_MEMBERS`
- [ ] Infraestrutura (IAM/Lambda/API Gateway/Layer de CA/Terraform) criada — **pendente**: não há IaC
      versionada neste repo; o desenho de `docs/ARQUITETURA.md` §6 é inferência, precisa ser
      confirmado com quem provisiona
- [ ] Tabela `tbcv4163_fatm_cogl_subg` criada no ambiente
- [x] Não há breaking changes — é a primeira release, não existe consumidor em produção. ⚠ Resolver
      antes de expor o BFF ao front: a rota `GET /conglomerados/{documento}/subgrupos` (ver seção de
      impacto)
