# Release — `<Nome do Projeto / Componente>`

## Tipo de Alteração

- [ ] Nova funcionalidade
- [ ] Bug
- [ ] Refatoração

> Descreva aqui, em uma frase, o tipo principal da release e se há mistura de correções/refatorações.

---

## O que foi alterado?

**Resumo:** `<X arquivos alterados, +Y / -Z linhas>`

**Contexto:** descreva de forma geral o que havia antes e o que passa a existir agora.

### Aplicação / Entry-point

**Arquivos principais:** `<caminho/do/main.py>`, `<outros entrypoints>`

Descreva:

- Tipo de aplicação (ex.: FastAPI, Flask, etc.)
- Handler (ex.: AWS Lambda, ECS, etc.)
- Endpoints básicos (ex.: health check)
- Middlewares relevantes (logging, contexto, autenticação, etc.)

### Rotas / Endpoints

| Verbo | Rota | Descrição |
| --- | --- | --- |
| `<VERBO>` | `/<base-path>/` | `<descrição breve da funcionalidade>` |
| `<VERBO>` | `/...` | `<descrição>` |
| `<VERBO>` | `/...` | `<descrição>` |

### Regras de Negócio

- Regras de validação (ex.: faixas, moedas, limites, etc.)
- Regras de cálculo, seleção, paginação ou composição de dados
- Normalizações ou tratamento em identificadores/documentos

### Infraestrutura

- Arquivos Terraform / IaC: `infra/main.tf`, `variables.tf`, etc.
- Políticas IAM, roles, permissões necessárias
- Configuração de Secrets/Parameters (ex.: `client_id` / `client_secret`, URLs)
- Variáveis de ambiente necessárias
- Uso de Layers, módulos compartilhados, etc.

### Testes

- Testes unitários: `<caminho dos testes unitários>`
- Testes de aceite / BDD: `<caminho das features/steps>`
- Fakes/fixtures para integrações externas

### Documentação e Qualidade

- Documentos: `docs/ARQUITETURA.md`, `docs/FLUXOS.md`, `docs/REGRAS.md`, etc.
- Configuração de ferramentas de qualidade (`black`, `ruff`, etc.)
- Arquivos de configuração de pipeline (`.jupies.yml`, `README.md`)

---

## O que motivou a alteração?

Descreva:

- Estado anterior (ex.: apenas esqueleto, MVP incompleto, bug crítico, etc.)
- Objetivo da mudança (ex.: entregar MVP, corrigir falhas, melhorar performance)
- Necessidade da área de negócio/usuário final
- Requisitos de segurança, compliance ou arquitetura que motivaram a release

---

## Há impacto em outros serviços/sistemas?

Liste e descreva brevemente.

- `<serviço/sistema>` — `<impacto>`

---

## Como testar essa mudança

### Pré-requisitos

- Versão mínima de linguagem (ex.: Python 3.12+)
- Variáveis de ambiente necessárias:
  - `ENVIRONMENT`
  - `<NOME_TABELA>`
  - `API_ROOT_PATH`
  - `<URLS_DE_SERVICOS_EXTERNOS>`
  - `<TOKEN_URL>`
  - `<AUTH_CLIENT_ID>`
  - `<AUTH_CLIENT_SECRET>`
  - Outros relevantes: `<LISTA_DE_CONFIGS>`

### Requests (passo a passo)

- Link/arquivo da collection (Postman, Insomnia, etc.)
- Exemplos de requisições para cada endpoint principal
- Dados mínimos para simular os cenários

```bash
# exemplo
curl -X <VERBO> "$API_URL/<base-path>/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ }'
```

### Cenários de testes

Baseados nas features em `<caminho>/features/` e `<caminho>/steps/`:

**Fluxo principal A (ex.: Salvar dados)**

- Cenário de sucesso com dados válidos
- Cenário sem dados obrigatórios → erro de validação
- Cenário com dados fora de faixa/limite → erro de regra
- Cenário com necessidade de confirmação (ex.: divergência acima do limite)

---

## Checklist

- [ ] Testes unitários passando (`<caminho>/tests/unit/`)
- [ ] Testes de aceite passando (`<caminho>/tests/acceptance/`)
- [ ] Lint e formatação OK (`ruff check`, `black --check`, etc.)
- [ ] `README.md` e documentação (`docs/`) atualizados
- [ ] Variáveis de ambiente e secrets configurados em todos os ambientes (dev/hom/prod)
- [ ] Infraestrutura (IAM/Lambda/Terraform/etc.) validada
- [ ] Não há breaking changes não documentados
