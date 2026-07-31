# Fluxos — Faturamento IRB/CV4

> Os bugs que impediam estes fluxos de rodar (ver histórico em
> `docs/AVALIACAO.md` §4) já foram corrigidos e estão cobertos por testes
> (`app/tests/unit/` e `app/features/`). Os diagramas abaixo descrevem o
> comportamento real e atual do código.

## 1. Visão geral dos dois fluxos

Uma única Lambda serve dois caminhos independentes, montados no mesmo app
FastAPI (`/irb-cra-faturamento/v1`):

- **SALVAR** (`POST /faturamento/{documento}`): o analista grava/edita
  valores de faturamento na tela; passa por validação de faixa/moeda e por
  um *gate* de divergência antes de persistir no DynamoDB.
- **BUSCAR** (`GET /faturamento/{documento}`, `GET /conglomerados/{documento}/
  subgrupos`): leitura *read-through* — tenta resolver o melhor valor
  combinando o que já está salvo com o que vem do Endpoint de Faturamento,
  aplicando as regras de negócio R1/R2/R3.

## 2. Fluxo SALVAR

```mermaid
sequenceDiagram
    participant Tela
    participant APIGW as API Gateway
    participant Route as api/routes.py
    participant Svc as domain/service.py
    participant Params as adapters/parametros.py
    participant Endpoint as adapters/endpoint.py
    participant Diverg as domain/divergencia.py
    participant Repo as adapters/repository.py
    participant Dynamo as DynamoDB

    Tela->>APIGW: POST /faturamento/{documento}<br/>(body + header X-RACF)
    APIGW->>Route: evento proxy → FaturamentoRequest
    Route->>Params: obter() snapshot (faixas, moedas, gate)
    Note over Params: token via STS antes da chamada<br/>(ver diagrama OAuth2, seção 4)
    Params-->>Route: {faixas, moedas, limiteVariacaoPercentual, gateDivergenciaAtivo}
    Route->>Svc: salvar(fat, repo, params, endpoint, metadados_compartilhados)

    loop para cada marcador do payload
        alt não foi editado na tela
            Svc->>Endpoint: buscar(subgrupo_doc)
            Endpoint-->>Svc: auditado/original/vigente (ou None)
        else foi editado na tela
            Svc->>Svc: usa metadados_compartilhados do topo do JSON
        end
        Svc->>Svc: normaliza (nivel, origem=BASE)
        Svc->>Svc: valida faixa (valor→faixa) e moeda
        Svc->>Repo: get_subgrupo(conglomerado_doc, subgrupo_doc)
        Repo->>Dynamo: get_item(cod_cogl, cod_subg)
        Dynamo-->>Repo: item existente (ou nada)
        Repo-->>Svc: MarcadorFaturamento existente ou None
        Svc->>Diverg: avaliar(novo, existente, limiteVariacaoPercentual)
        Diverg-->>Svc: lista de divergências (vazia se ok)
    end

    alt há divergência(s) não confirmada(s)
        Svc-->>Route: raise ConfirmacaoNecessaria(divergencias)
        Route-->>Tela: 409 + lista de divergências
    else sem divergência (ou já confirmada)
        Svc->>Repo: save(fat)
        Repo->>Dynamo: batch_writer.put_item por marcador<br/>(upsert incremental, roll atual→anterior)
        Repo-->>Svc: ok
        Svc-->>Route: Faturamento salvo
        Route-->>Tela: 201 + faturamento_out(persistido=true)
    end
```

## 3. Fluxo BUSCAR

```mermaid
sequenceDiagram
    participant Tela
    participant APIGW as API Gateway
    participant Route as api/routes_buscar.py
    participant Svc as domain/service_buscar.py
    participant NJ6 as adapters/nj6.py
    participant Repo as adapters/repository.py
    participant Dynamo as DynamoDB
    participant Endpoint as adapters/endpoint.py
    participant Eleicao as domain/eleicao.py
    participant Catalogo as adapters/parametros.py

    alt GET /faturamento/{documento} - via read-through
        Tela->>APIGW: GET /faturamento/{documento} (query aba, limit, cursor)
        APIGW->>Route: evento proxy
        Route->>Svc: obter_faturamento(documento, aba, repo, nj6, endpoint, catalogo, limit, cursor)
        Svc->>NJ6: get_por_documento(documento)
        Note over NJ6: token via STS<br/>(ver diagrama OAuth2)
        NJ6-->>Svc: Conglomerado (subgrupos + integrantes)
        Svc->>Repo: get_conglomerado(cabeca_documento_raiz)
        Repo->>Dynamo: query(cod_cogl = ...)
        Dynamo-->>Repo: itens salvos
        Repo-->>Svc: marcadores salvos por subgrupo
        Svc->>Catalogo: obter()
        Catalogo-->>Svc: {faixas, moedas}
        Svc->>Svc: define alvos da aba (CONGLOMERADO paginado, ou SUBGRUPO=matriz)

        par busca em paralelo (ThreadPoolExecutor, até 10 workers)
            Svc->>Endpoint: buscar(subgrupo_1)
            Svc->>Endpoint: buscar(subgrupo_2)
            Svc->>Endpoint: buscar(subgrupo_N)
        and
            Endpoint->>Eleicao: eleger(análises cruas, asof)
            Eleicao-->>Endpoint: ResultadoFaturamento eleito (ou None)
        end
        Endpoint-->>Svc: dict {subgrupo → ResultadoFaturamento | None}

        loop para cada alvo
            alt banco em quarentena com "anterior" válido
                Svc->>Svc: elege o valor "anterior", ignora R1/R2/R3
            else banco válido (R1/R2/R3 + idade<=24m) E endpoint válido
                Svc->>Svc: desempata pelo data_ref_balanco mais recente
            else só banco válido
                Svc->>Svc: usa o banco
            else só endpoint válido
                Svc->>Svc: usa o resultado do endpoint
            else nenhum válido
                Svc->>Svc: marcador MANUAL (tela pede preenchimento)
            end
            Svc->>Svc: enriquece faixa_descricao via catálogo
        end
        Svc-->>Route: Faturamento agregado + paginação
        Route-->>Tela: 200 + faturamento_out(persistido=?)
    else GET /conglomerados/{documento}/subgrupos
        Tela->>APIGW: GET /conglomerados/{documento}/subgrupos
        APIGW->>Route: evento proxy
        Route->>Svc: listar_subgrupos(documento, nj6)
        Svc->>NJ6: get_por_documento(documento)
        NJ6-->>Svc: Conglomerado (hierarquia crua)
        Svc-->>Route: Conglomerado
        Route-->>Tela: 200 + conglomerado_out (tabela de integrantes)
    end
```

## 4. Autenticação OAuth2 (STS) — compartilhada pelos 3 adapters HTTP

Genérico: `adapters/nj6.py`, `adapters/endpoint.py` e `adapters/parametros.py`
usam o mesmo `TokenProvider` (injetado via `api/deps.py::get_token_provider`,
singleton por invocação quente da Lambda).

```mermaid
sequenceDiagram
    participant Adapter as Adapter (NJ6 / Endpoint / Parâmetros)
    participant TP as adapters/auth.py<br/>(OAuth2TokenProvider)
    participant Mgr as core/oauth2.py<br/>(OAuth2Manager)
    participant STS

    Adapter->>TP: auth_headers()
    TP->>Mgr: get_token()
    alt token em cache e ainda válido (margem de 60s)
        Mgr-->>TP: access_token (do cache em memória)
    else token ausente ou expirado
        Mgr->>STS: POST /api/oauth/token<br/>(grant_type=client_credentials, client_id, client_secret)
        STS-->>Mgr: {access_token, expires_in}
        Mgr->>Mgr: cacheia em memória (chave = token_url)
        Mgr-->>TP: access_token
    end
    TP-->>Adapter: {"Authorization": "Bearer <token>"}
    Adapter->>Adapter: anexa header à requisição HTTP real
```

## 5. Cascata de eleição R1 → R2 → R3 (`domain/eleicao.py`)

A primeira regra com pelo menos um candidato elegível vence — não há
combinação entre regras.

```mermaid
flowchart TD
    Start(["Análises cruas do Endpoint\n+ histórico de faturamento por análise"]) --> Balanco["Para cada análise: acha o balanço\nmais recente com dataReferencia <= asof\ne idade <= 24 meses"]
    Balanco --> R1{"R1: auditado E original E vigente\nE categoria em (2,4,3,5,6)?"}
    R1 -->|"sim, >=1 candidato"| DesR1["Desempate R1: prioridade de categoria\n→ atualizado mais recente\n→ balanço mais recente"]
    DesR1 --> Fim(["Elege 1 valor\n(ResultadoFaturamento)"])
    R1 -->|"nenhum"| R2{"R2: auditado E vigente\nE situação=Aprovado(3)?"}
    R2 -->|"sim, >=1 candidato"| DesR2["Desempate R2: balanço mais recente"]
    DesR2 --> Fim
    R2 -->|"nenhum"| R3{"R3: original E vigente\nE Aprovado(3)\nE categoria NÃO em (1,6,7,8,9)?"}
    R3 -->|"sim, >=1 candidato"| DesR3["Desempate R3: MAIOR valor"]
    DesR3 --> Fim
    R3 -->|"nenhum"| Manual(["Nenhuma regra passou → None\n(marcador vira MANUAL na tela)"])

    Nota1["⚠ 'original' assume indicadorFatorPonderado=False;\npolaridade ainda não confirmada com o time do Endpoint\n(ver AVALIACAO.md §6, item 17 - pendência de negócio)"]
    Nota2["✅ resolucao_marcador.py::valida_regras_banco chama\neleicao.qual_regra_passa() — mesma função, não reimplementa\n(ver AVALIACAO.md §6, item 9)"]
    R1 -.-> Nota1
    R3 -.-> Nota1
    Fim -.-> Nota2
```

## 6. Tratamento de erros (domínio → HTTP)

Mapeamento único, registrado em `api/errors.py::register_exception_handlers`,
resolvido pela MRO da exceção (subclasses de `ErroValidacao` caem no handler
de `ErroValidacao`, preservando `type(e).__name__` na resposta):

| Exceção de domínio | Status HTTP | Quando |
|---|---|---|
| `ConfirmacaoNecessaria` | 409 | Divergência detectada no SALVAR sem confirmação prévia (`confirmado_divergencia=false`) |
| `NaoEncontrado` | 404 | Documento não resolvido no NJ6 |
| `ErroValidacao` (e subclasses, ex. `FaixaObrigatoria`) | 422 | Falha de validação de regra de negócio (faixa, moeda, cursor inválido, etc.) |
| `DominioError` (genérica) | 400 | Erro de domínio não mais específico — logado como aviso, pois "não deveria vazar sem tratamento" |
| `Exception` (não mapeada) | 500 | Qualquer exceção não prevista — logada com stack trace, resposta genérica sem detalhe interno |
