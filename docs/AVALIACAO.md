# Avaliação do código — Faturamento IRB/CV4

> **Status desta avaliação**: todas as recomendações de P0 a P3 **já foram
> corrigidas**, exceto o item 17 (§8), que depende de confirmação de negócio
> do time do Endpoint e não é algo que se resolve só no código. Tudo coberto
> por testes automatizados (`app/tests/unit/` + `app/features/`) e por
> `ruff`/`black` (`app/pyproject.toml`). O texto abaixo é mantido como
> registro histórico da análise original — cada item em §4/§5/§6/§7/§8 tem
> uma nota de status (✅ corrigido / não alterado / não corrigível só em
> código) para deixar rastreável o que mudou e por quê.

## 1. Contexto

Este documento avalia o código-fonte atual deste repositório: uma Lambda
FastAPI + Mangum que expõe dois fluxos (SALVAR e BUSCAR) para a tela de
faturamento do CRA, dentro do domínio de gestão de conglomerados/subgrupos
econômicos do Itaú.

Importante: este repositório **não é um snapshot orgânico** de um projeto.
Conforme `../RECONSTRUCAO.md`, todo o código foi recriado por agentes de IA a
partir de 2402 frames de um vídeo de 240s da IDE de outra pessoa, sem OCR,
com gaps honestamente documentados (ex.: `api/schemas.py` nunca foi aberto no
vídeo; `domain/eleicao.py` capturado só até a linha ~190).

Por isso, cada problema abaixo é classificado quanto à origem provável:

- **[RECONSTRUÇÃO]** — muito provavelmente um artefato do processo de
  transcrição/merge (duplicação de bloco, comentário de OCR, etc.), não uma
  falha de quem escreveu o código original.
- **[LÓGICA]** — um bug ou decisão de design que muito provavelmente já
  existia no código original (ou é indiferente à origem, porque o efeito é o
  mesmo em produção).

A pergunta real por trás desta avaliação não é "o vídeo foi bem transcrito?",
e sim: **a arquitetura e as práticas de código aqui correspondem ao que se
esperaria de um desenvolvedor Senior em um banco como o Itaú?** A resposta
curta está no resumo executivo abaixo.

## 2. Resumo executivo

**A arquitetura está no nível certo. A execução, no estado atual do
repositório, não está.**

O design é genuinamente bom: separação hexagonal limpa (`api` → `domain` →
`adapters` → `core`), inversão de dependência via `Protocol` (o domínio não
importa `boto3`, `httpx` nem FastAPI), mapeamento centralizado de exceção→HTTP,
logging estruturado pensado para Datadog com correlação de request, e
docstrings que documentam o "porquê" das regras de negócio — inclusive
sinalizando honestamente pendências ainda não confirmadas com outros times
(ex.: `eleicao.py`). Isso é exatamente o tipo de disciplina que se espera de
um Senior.

Só que, lendo o código linha a linha (não só a estrutura), encontrei **5
bugs que impediam a Lambda de subir ou quebravam um fluxo inteiro** (2 eram
prováveis artefatos de reconstrução — duplicação de definição de classe/função,
inofensivos porque a última definição vence em Python — mas **3 eram bugs
reais de lógica** que quebrariam em produção independente da origem: um erro
de sintaxe que impedia o import do módulo, um atributo inexistente acessado
no fluxo de SALVAR, e uma chamada de método na classe `Protocol` em vez de na
instância no fluxo de BUSCAR). Some a isso **zero testes automatizados** — e
nenhum desses bugs teria sobrevivido a uma suíte mínima ou a um `python -m
py_compile` em CI.

**Atualização**: os 5 bugs críticos foram corrigidos, e as recomendações de
P1 a P3 também (unificação da cascata R1/R2/R3, mascaramento de CPF/CNPJ nos
logs, config centralizada em `settings`, `service_buscar.py` dividido em
módulos menores, `ruff`/`black` aplicados a todo o código) — só o item 17
(§8) fica de fora, por depender de confirmação de negócio externa. Agora há
uma suíte de testes unitários (pytest, 76 testes) e de aceitação/BDD
(behave, 9 cenários) cobrindo o domínio e os dois fluxos — ver §8. A Lambda
importa e sobe normalmente (`from app.main import app, handler`).

**Veredito (histórico, no momento em que a avaliação foi feita)**: um Senior
não entregaria isto no estado em que o repositório estava — não pelo design
(que está correto), mas porque nenhum destes bugs passaria por um code
review real ou por um pipeline de CI com um teste de smoke básico. A
ausência de testes era, sozinha, o maior desvio do padrão esperado: a
arquitetura escolhida (funções puras + `Protocol`) é extremamente testável, e
não ter nenhum teste era uma escolha que este design não pedia. Esse ponto
específico também já foi endereçado (ver §8).

## 3. Pontos fortes

- **Arquitetura hexagonal correta**: `domain/` não depende de framework,
  banco ou biblioteca HTTP — define `Protocol`s (`Repositorio`, `NJ6`,
  `Endpoint`, `Catalogo`, `TokenProvider`) e os adapters os implementam por
  duck typing. Inversão de dependência de livro-texto.
- **Separação SALVAR/BUSCAR deliberada**: `domain/service.py` e
  `domain/service_buscar.py` são módulos distintos propositalmente, para não
  misturar os protocolos de leitura e escrita — um comentário no topo do
  arquivo explica exatamente essa decisão.
- **Tratamento de erros centralizado**: hierarquia `DominioError` →
  `NaoEncontrado`/`ErroValidacao`/`ConfirmacaoNecessaria` (`domain/errors.py`)
  mapeada uma única vez para HTTP em `api/errors.py`, usando a MRO do Python
  para resolver o handler certo por subclasse — evita `try/except` espalhado
  pelas rotas.
- **Logging estruturado bem desenhado**: `core/logging.py` define uma
  convenção clara (evento de negócio vs. técnico vs. erro), com
  `bind_context`/`contextvars` para correlacionar todos os logs de uma
  invocação pelo `request_id`, e enriquecimento opcional com
  `dd.trace_id`/`dd.span_id` do `ddtrace`.
- **Documentação inline honesta**: `domain/eleicao.py` documenta a cascata
  R1/R2/R3 citando a decisão de negócio de origem ("Repasse 18/06 + RN06") e
  sinaliza explicitamente pendências não confirmadas (ex.: a polaridade de
  `indicadorFatorPonderado`) em vez de escondê-las.
- **Nomenclatura consistente**: `snake_case` para módulos/funções,
  `PascalCase` para classes, prefixo `_` para funções privadas, termos de
  negócio em português (`faixa`, `divergência`, `eleição`) — consistente com
  a linguagem ubíqua do domínio.
- **Dependências fixadas** (`==`) e nenhum segredo real hardcoded — `.env` é
  ignorado pelo git, `.env.example` só tem placeholders locais.
- **Validação de paginação bem feita**: `limit: int = Query(..., ge=1,
  le=LIMIT_MAXIMO)` e decodificação de cursor defensiva
  (`_decode_cursor` levanta `ErroValidacao` em vez de deixar estourar).

## 4. Problemas críticos (quebravam o boot ou um fluxo inteiro) — ✅ CORRIGIDOS

### 4.1 `domain/service_buscar.py` não compilava — **[LÓGICA]** — ✅ corrigido

`_log_resolucao` (linhas 420-435) chama `log_event(...)` repetindo as mesmas
keywords (`origem_dados` 3x, `endpoint` 2x, `manual` 2x) na mesma chamada.
Isso é um `SyntaxError` do próprio parser do Python ("keyword argument
repeated"), não um erro de runtime — o módulo **nem chega a ser importado**.
Como `main.py` importa `api/routes_buscar` que importa `domain/service_buscar`,
**a Lambda inteira falha no cold start**, não só o caminho GET.

```python
log_event(
    _logger, "faturamento.buscar.resolvido",
    ...
    origem_dados="BASE" if por_origem[Origem.BASE] else "PREVIEW",
    endpoint=por_origem[Origem.ENDPOINT],
    manual=por_origem[Origem.MANUAL],
    origem_dados="BASE" if por_origem[Origem.BASE] else "PREVIEW",  # repetido
    ...
)
```

**Correção aplicada**: keywords duplicadas removidas; validado com
`ast.parse`/`python -m py_compile` e coberto por
`tests/unit/test_regressao_bugs_criticos.py::test_service_buscar_compila_sem_erro_de_sintaxe`.

### 4.2 `domain/service.py` acessava um atributo que não existe — **[LÓGICA]** — ✅ corrigido

`_resolver_metadados` (linha 83) faz `if m.nao_foi_editado and endpoint is
not None:`, mas `MarcadorFaturamento` (`domain/models.py`) **não define**
nenhum campo `nao_foi_editado` — o campo que existe é `faturamento_modificado`
(preenchido a partir do request em `api/schemas.py::to_domain`). Como
`MarcadorFaturamento` é uma `@dataclass` comum (sem `__getattr__` de
fallback), acessar `m.nao_foi_editado` levanta `AttributeError` — **e essa
função roda para todo marcador em todo POST /faturamento/{documento}**, ou
seja, o fluxo de SALVAR quebra sempre, para qualquer payload.

**Correção aplicada**: `m.nao_foi_editado` trocado por
`not m.faturamento_modificado`; coberto por
`tests/unit/test_service_salvar.py::test_nao_editado_busca_metadados_no_endpoint`
e pelo cenário de BDD "Divergência confirmada é aceita" (que só passa se o
SALVAR completo rodar sem `AttributeError`).

### 4.3 `domain/service_buscar.py` chamava o método na classe `Protocol`, não na instância — **[LÓGICA]** — ✅ corrigido

Linha 96: `faixas = (Catalogo.obter() or {}).get("faixas") or []` — chama
`obter()` na classe `Catalogo` (o `Protocol`, cujo corpo é só `...`) em vez de
no parâmetro `catalogo` recebido pela função. Isso levanta `TypeError: obter()
missing 1 required positional argument: 'self'` — quebra **todo** o fluxo
BUSCAR (tanto `GET /faturamento/{documento}` quanto, indiretamente, qualquer
chamada que passe por `obter_faturamento`), independente do bug 4.1.

**Correção aplicada**: `Catalogo.obter()` trocado por `catalogo.obter()`;
coberta por
`tests/unit/test_service_buscar.py::test_usa_o_catalogo_recebido_por_parametro_nao_a_classe_protocol`
e por `tests/unit/test_regressao_bugs_criticos.py`.

### 4.4 `tenacity` usado mas ausente de `requirements.txt` — **[LÓGICA]** — ✅ corrigido

`core/retry.py` faz `from tenacity import (...)` e é importado por
`nj6.py`, `endpoint.py` e `parametros.py` — mas `tenacity` não consta em
`requirements.txt`. Um `pip install -r requirements.txt` limpo seguido de
qualquer chamada a esses adapters resulta em `ModuleNotFoundError`.

**Correção aplicada**: `tenacity==8.2.3` adicionado a `requirements.txt`;
`pip install -r requirements.txt` seguido de `from app.main import app,
handler` foi validado com sucesso.

### 4.5 `adapters/endpoint.py` — bug de precedência de operador que zerava os dados — **[LÓGICA]** — ✅ corrigido

```python
spreads = data.get("data") or data.get("spreads") or data if isinstance(data, list) else []
```

Em Python, o operador ternário tem precedência **menor** que `or`, então isso
é avaliado como:

```python
(data.get("data") or data.get("spreads") or data) if isinstance(data, list) else []
```

Ou seja:
- Se `data` for uma **lista** (o próprio comentário do código diz "pode estar
  em 'data' ou direto" — cobrindo justamente esse caso): `data.get(...)`
  lança `AttributeError` (lista não tem `.get`), capturado pelo `except
  Exception` amplo do método chamador e tratado como "sem dados" (`None`).
- Se `data` for um **dict** (o caso normal, ex. `{"data": [...]}`): a
  condição `isinstance(data, list)` é falsa, então o resultado é **sempre
  `[]`** — os spreads reais dentro de `data["data"]` são silenciosamente
  descartados, sem nenhum erro.

Na prática: o adapter de Endpoint **nunca consegue devolver spreads reais**
com nenhum dos dois formatos de resposta cobertos pelo próprio comentário —
ele degrada silenciosamente para "sem balanço" (`MANUAL` na tela) o tempo
todo. Como o `except Exception: return None` em `HttpEndpoint.buscar` (linha
76-78) mascara qualquer exceção como "sem dado", isso nunca aparece como
erro nos logs de nível ERROR — só como ausência de dado.

**Correção aplicada**: a extração foi reescrita com a precedência correta e
extraída para uma função pura `_extrair_spreads(data)` (em vez de ficar
embutida no meio da chamada HTTP), especificamente para ser testável sem
mockar rede. Coberta por 4 testes em
`tests/unit/test_regressao_bugs_criticos.py` (lista crua, `{"data": [...]}`,
`{"spreads": [...]}` e formato não reconhecido).

## 5. Problemas de alto risco (não bloqueiam o boot, mas são sérios) — ✅ todos corrigidos

### 5.1 `USAR_MOCK_INTEGRACOES` documentado, mas nunca lido — **[LÓGICA]** — ✅ corrigido

`core/settings.py` definia e calculava `usar_mock_integracoes` (default
`"1"`), e o docstring de `api/deps.py` afirmava um switch mock/real que não
existia — `get_nj6`, `get_endpoint`, `get_parametros` e `get_catalogo`
**sempre** construíam as classes `Http*`/`ParametrosClient` reais.

**Correção aplicada**: em vez de construir um switch mock/adapter em Python
que duplicaria o que o stack `mocks/` (docker-compose) já faz via HTTP, o
campo fantasma foi removido de `Settings` e os docstrings de `settings.py`/
`deps.py` foram reescritos para descrever o mecanismo real: local aponta
`NJ6_BASE_URL`/`ENDPOINT_BASE_URL`/`PARAMETROS_BASE_URL`/`TOKEN_URL` para o
`mock-api` do `docker-compose`; produção aponta para os serviços reais — o
código do adapter é o mesmo nos dois casos.

### 5.2 Possível exposição de CPF/CNPJ em log — risco de LGPD — **[LÓGICA]** — ✅ corrigido

`adapters/nj6.py` logava a **URL completa da requisição** (com o
`documento` na querystring) **e** o campo `documento` de novo, em texto
puro, indo para o Datadog (SaaS terceiro).

**Correção aplicada**: novo helper `core/mascaramento.py::mascarar_documento()`
(mantém só os últimos 4 dígitos), usado em todos os `log_event`/`logger.exception`
de `nj6.py` e `endpoint.py` que carregavam `documento`; a URL completa deixou
de ser logada (só o evento + documento mascarado + correlation_id). A
mensagem de erro devolvida ao próprio chamador (`NaoEncontrado`) mantém o
documento em texto puro de propósito — não é um log para terceiro, é a
resposta HTTP para quem já submeteu aquele documento.

### 5.3 Zero testes automatizados, sem CI, sem linter — **[possivelmente LÓGICA + RECONSTRUÇÃO]** — parcialmente corrigido

> ✅ **Atualização**: `app/tests/unit/` (pytest, 76 testes cobrindo
> `eleicao.py`, `divergencia.py`, `faixa.py`, `service.py`, `service_buscar.py`,
> `paginacao.py`, `resolucao_marcador.py` e os 5 bugs críticos como
> regressão) e `app/features/` (behave/Gherkin, 9 cenários de BDD para
> SALVAR e BUSCAR) existem — ver `app/requirements-tests.txt`. `ruff` +
> `black` também foram configurados e aplicados em todo o código
> (`app/pyproject.toml`, `.pre-commit-config.yaml`) — ver §6/§8.
> **CI ainda não existe** (não há `.github/workflows/` rodando isso
> automaticamente a cada PR) — isso continua em aberto.

## 6. Problemas moderados — ✅ todos corrigidos

- ~~**`ParametrosClient` definida duas vezes** em `adapters/parametros.py`~~
  — **[RECONSTRUÇÃO, inofensivo]** — ✅ **corrigido**: a primeira definição
  morta (incompleta, com stubs `NotImplementedError` sobrepostos) foi
  removida; só resta a versão correta e completa.
- ~~**`setup_logging()` definida duas vezes** em `core/logging.py`~~ —
  **[RECONSTRUÇÃO, inofensivo]** — ✅ **corrigido**: a primeira definição
  quebrada (que continha um comentário literal de falha de OCR — *"noot
  nemoveHandler(h)"*) foi removida; só resta a versão correta e completa.
- ~~**Cascata R1/R2/R3 duplicada com lógica diferente**~~ — **[LÓGICA, risco
  real]** — ✅ **corrigido**: extraída uma única função
  `domain/eleicao.py::qual_regra_passa(auditado, original, vigente)` — o
  núcleo comum da cascata. `domain/resolucao_marcador.py::valida_regras_banco`/
  `qual_regra_passou` (antes em `service_buscar.py`) agora chamam essa
  função em vez de reimplementar o cascateamento à parte. `eleicao.eleger`
  continua com sua lógica adicional de categoria/situação/desempate por
  cima (não removida, pois é exclusiva da eleição entre várias análises).
- ~~**`_criar_contexto_ssl()` duplicada verbatim**~~ em `nj6.py` e
  `endpoint.py` — ✅ **corrigido**: extraída para
  `core/ssl_context.py::criar_contexto_ssl()`, importada pelos dois adapters.
- ~~**Acesso a config vazando por `os.environ` direto**~~ (`ITAU_API_KEY`
  em `nj6.py`/`endpoint.py`) — ✅ **corrigido**: `Settings` ganhou os campos
  `itau_api_key`/`itau_correlation_id`/`itau_flow_id`; `nj6.py`/`endpoint.py`
  agora leem `settings.itau_api_key`, e `adapters/auth.py::build_token_provider`
  passa os três explicitamente para `OAuth2Manager` (em vez de depender do
  `default_factory` dele lendo `os.environ` por baixo dos panos).
- ~~**`httpx`/`pydantic-settings` fixados mas não usados**~~ — ✅
  **decidido e corrigido**: removidos de `requirements.txt`. Migrar de
  verdade para `httpx` (reescrever 3 adapters + tratamento de erro) ou para
  `pydantic-settings` (BaseSettings) traria risco desproporcional ao ganho
  numa passada de limpeza — a decisão registrada foi remover a dependência
  não usada, não adotá-la.
- ~~**Sem validação de formato do `documento`**~~ no boundary da API — ✅
  **corrigido**: `api/validacao.py` define `DOCUMENTO_PATTERN` (só dígitos,
  sem exigir dígito verificador), aplicado via `Path(..., pattern=...)` nas
  3 rotas que recebem `documento`. Entrada malformada agora falha com 422
  imediato, não com um 404 do NJ6 rio abaixo. (Nota: a faixa de tamanho fixa
  de 9–14 dígitos que existiu nesse validador foi removida depois — ver
  `R-API-001` em `docs/REGRAS.md`.)
- **Logging verboso nos adapters HTTP** — não alterado nesta rodada
  (reduzir o volume de eventos técnicos é uma call de produto/observabilidade,
  não um bug; mantido como nota, não como pendência corrigida).
- **Polaridade de regra de negócio não confirmada em produção**
  (`eleicao.py::_original()`) — não alterado: depende de confirmação do
  time do Endpoint (Deus/Felipe), não é algo que se resolve só no código
  (ver §9/item 17 das recomendações).

## 7. Problemas menores — ✅ corrigidos (exceto nomenclatura de adapters)

- ~~**Espaçamento inconsistente de linhas em branco**~~ (artefatos de
  transcrição) — ✅ **corrigido**: `black` (com `preview = true` para manter
  os stubs de `Protocol` compactos, ex. `def obter(self) -> dict: ...`) foi
  aplicado a todo o código; `ruff check` está limpo.
- Sem convenção fixa de prefixo para classes de adapter (`Http*` vs.
  `_Cliente*`) — não alterado (renomear classes públicas é uma mudança de
  API interna de baixo valor isolada; não fazia sentido nesta rodada sem
  tocar em mais nada ao redor).
- ~~**`domain/service_buscar.py` (435 linhas) acumulava responsabilidades
  demais**~~ — ✅ **corrigido**: dividido em três módulos por
  responsabilidade — `domain/service_buscar.py` (orquestração do fluxo,
  ~150 linhas), `domain/paginacao.py` (paginação/cursor + seleção de alvos
  por aba) e `domain/resolucao_marcador.py` (banco vs. Endpoint vs. MANUAL,
  incluindo a validação R1/R2/R3 do item acima). Cada módulo agora tem
  testes unitários próprios (`tests/unit/test_paginacao.py`,
  `tests/unit/test_resolucao_marcador.py`).

## 8. Recomendações priorizadas

**P0 — bloqueadores de boot/funcionamento — ✅ todos corrigidos:**
1. ✅ Corrigido o `SyntaxError` em `service_buscar.py::_log_resolucao` (§4.1).
2. ✅ Corrigido `m.nao_foi_editado` → `not m.faturamento_modificado` em
   `service.py::_resolver_metadados` (§4.2).
3. ✅ Corrigido `Catalogo.obter()` → `catalogo.obter()` em
   `service_buscar.py::obter_faturamento` (§4.3).
4. ✅ Adicionado `tenacity==8.2.3` a `requirements.txt` (§4.4).
5. ✅ Corrigida a precedência de operador em `endpoint.py` (extraída para
   `_extrair_spreads()`, testável isoladamente) (§4.5).

**P1 — risco de produção — em aberto:**
6. Implementar de fato o switch `USAR_MOCK_INTEGRACOES` em `deps.py`, ou
   remover a documentação da feature (§5.1).
7. Mascarar/tokenizar `documento` (CPF/CNPJ) antes de logar (§5.2).
8. ✅ **Feito**: suíte de testes unitários (pytest, `app/tests/unit/`) para
   `eleicao.py`, `divergencia.py`, `faixa.py`, `service.py`,
   `service_buscar.py`, incluindo regressão dos 5 bugs do §4 — e testes de
   aceitação/BDD (`behave`, `app/features/`) para os fluxos SALVAR e BUSCAR
   completos. **Ainda falta**: CI (`.github/workflows/`) rodando essa suíte
   automaticamente a cada PR (§5.3).

**P2 — dívida técnica — ✅ todos corrigidos:**
9. ✅ Unificada a cascata R1/R2/R3: `eleicao.qual_regra_passa()` é agora a
   única fonte de verdade, chamada tanto por `eleger()` quanto por
   `resolucao_marcador.py` (§6).
10. ✅ Código morto duplicado removido de `parametros.py` e `logging.py` (§6).
11. ✅ `_criar_contexto_ssl()` extraída para `core/ssl_context.py` (§6).
12. ✅ `ITAU_API_KEY`/`ITAU_CORRELATION_ID`/`ITAU_FLOW_ID` roteados por
    `settings` (§6).
13. ✅ Decidido remover `httpx`/`pydantic-settings` de `requirements.txt`
    (não usados; migrar de verdade seria desproporcional numa limpeza) (§6).

**P3 — polimento — ✅ corrigidos (exceto item 17):**
14. ✅ `ruff` + `black` configurados (`app/pyproject.toml`) e aplicados a
    todo o código; `.pre-commit-config.yaml` na raiz para rodar nos commits.
15. ✅ `documento` (CPF/CNPJ/CGI) validado no boundary da API via
    `Path(..., pattern=...)` (§6).
16. ✅ `service_buscar.py` dividido em `service_buscar.py` (orquestração) +
    `paginacao.py` + `resolucao_marcador.py` (§7).
17. **Não corrigido — não é possível só no código**: resolver a pendência de
    polaridade de `indicadorFatorPonderado` em `eleicao.py` exige
    confirmação do time do Endpoint (Deus/Felipe) sobre o contrato real do
    campo; nenhuma leitura de código resolve isso. Mantido documentado
    (`eleicao.py` linha ~19-27) até essa confirmação acontecer.

## 9. Nota metodológica

Esta avaliação foi feita originalmente por **leitura estática** de todos os
módulos em `app/src/app/` — não era possível executar a aplicação de ponta a
ponta porque o bug §4.1 impedia o próprio import do módulo (e os bugs
§4.2/§4.3 impediriam qualquer chamada real aos dois endpoints principais
mesmo depois de corrigido o import). Os bugs listados foram confirmados por
leitura direta do código-fonte (não apenas por relatórios de exploração
automatizada), comparando assinaturas de função com o uso real dos campos e
checando a precedência de operadores manualmente.

**Atualização pós-correção**: depois de aplicar P0 a P3 (exceto o item 17,
que não é um bug de código), a aplicação foi importada e executada de
ponta a ponta em ambiente limpo (`pip install -r requirements.txt` +
`from app.main import app, handler` com sucesso), e a suíte de testes —
`pytest tests/unit` (76 testes) e `behave features` (9 cenários / 57 steps)
— roda integralmente verde, junto com `ruff check` (limpo) e
`black --check` (estável). Nenhuma correção de P0-P3 mudou o comportamento
observável dos endpoints (mesmos testes de antes continuam passando); o
que mudou foi estrutura interna (módulos menores, config centralizada,
dependência morta removida) e dois reforços de segurança (mascaramento de
log, validação de formato na API).
