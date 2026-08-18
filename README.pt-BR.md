# DecisionsSearch 🔍

> **Servidor de Memória Híbrida para Agentes de IA** — um servidor MCP com memória compartilhada e persistente (Neo4j + Qdrant) e um investigador autônomo de erros de CI/CD que encontra causas-raiz e propõe correções.

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python)](https://python.org)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green?logo=json)](https://modelcontextprotocol.io)
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen)]()
[![License](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker)]()

🇺🇸 **[Read in English](README.md)**

## O que é o DecisionsSearch

Agentes de IA de código esquecem tudo no instante em que uma sessão termina. A próxima sessão — sua ou de um colega — re-deriva o mesmo contexto, re-discute as mesmas decisões e repete erros que o time já corrigiu uma vez. Pipelines de CI/CD têm o mesmo ponto cego: erros acontecem, são triados manualmente, e a ligação entre "esse erro" e "o PR que causou isso" se perde.

**O DecisionsSearch é uma camada de memória persistente e consultável entre seus agentes de IA e um grafo de conhecimento.** Ele dá aos agentes três coisas que eles não têm sozinhos:

1. **Memória durável entre sessões** — decisões, regras de negócio, padrões de código e histórico de PRs sobrevivem depois que a janela de chat fecha. O Neo4j guarda as relações (o que implementa o quê, o que substituiu o quê); o Qdrant permite busca semântica sobre tudo isso.
2. **Um vocabulário estruturado para "o que vale a pena lembrar"** — não é um despejo bruto de transcrição, mas categorias tipadas (regra de negócio, decisão arquitetural, padrão de código, registro de PR, episódio de task) que continuam úteis meses depois.
3. **Investigação autônoma de erros** — aponte seu CI/CD para o webhook do DecisionsSearch, e ele encontra os PRs suspeitos, roda um agente de código pra investigar a causa-raiz, e pode abrir um PR de correção sozinho.

## Para que usar

- Você roda o Claude Code (ou outro agente compatível com MCP) numa base de código que mexe com frequência, e está cansado de reexplicar a mesma arquitetura e as mesmas regras toda sessão.
- Vários agentes/desenvolvedores trabalham na mesma base de código e precisam de uma fonte de verdade compartilhada sobre *por que* as coisas são como são, não só *o que* o código faz.
- Você quer que seu CI/CD faça a triagem inicial de erros antes de um humano olhar.

**Não use para:** um script pontual, um protótipo descartável, ou como substituto da sua documentação/wiki de verdade — o DecisionsSearch complementa docs estruturados, não os substitui (veja os arquivos `.decisionssearch/` abaixo).

## Início Rápido

### Pré-requisitos

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/) (recomendado) ou pip
- Docker (para Neo4j + Qdrant no modo full)

### Instalar

```bash
git clone https://github.com/Renzo-Tognella/DecisionsSearch.git
cd DecisionsSearch
uv sync
```

### Configurar

```bash
cp .env.example .env
cp config/decisionssearch.yaml.example config/decisionssearch.yaml
```

Edite `.env` com suas chaves de API e `config/decisionssearch.yaml` para o seu setup.

### Rodar

**Modo full** (Neo4j + Qdrant, recomendado — busca mais rica, travessia de grafo):

```bash
# Sobe a infraestrutura
docker compose up -d

# Inicializa a coleção vetorial (idempotente — seguro rodar de novo)
uv run python -m scripts.bootstrap_qdrant

# Sobe o servidor (HTTP + MCP na porta 8000)
uv run decisionssearch
```

O servidor HTTP/MCP atual usa a composição full e exige Neo4j + Qdrant. O campo
`mode` foi mantido por compatibilidade de configuração; definir `mode: light`
não ativa hoje um servidor somente JSONL. JSONL é usado para landing zone,
snapshots e estado operacional local; o benchmark possui um backend local
explícito separado.

### Verificar

```bash
# O endpoint MCP responde (406 sem os headers certos de MCP é esperado — significa que a rota está viva)
curl http://localhost:8000/api/health   # readiness real vive sob /api
curl http://localhost:8000/mcp/
```

## Conectando seu Agente

**Local, stdio (mais simples para uso pessoal):**

```json
{
  "mcpServers": {
    "decisionssearch": {
      "command": "uv",
      "args": ["--directory", "/caminho/para/DecisionsSearch", "run", "decisionssearch-mcp"]
    }
  }
}
```

**Local ou remoto, HTTP (necessário se o servidor já roda como processo persistente, ex.: via `uv run decisionssearch`):**

```json
{
  "mcpServers": {
    "decisionssearch": { "url": "http://localhost:8000/mcp" }
  }
}
```

Coloque isso no `.mcp.json` de um projeto (escopo de projeto) ou na sua config MCP global. **Servidores MCP só são carregados quando uma sessão inicia** — depois de adicionar ou mudar essa config, abra uma sessão nova do agente naquele projeto em vez de esperar as tools aparecerem no meio da sessão atual.

### Memórias separadas por projeto

Nas tools de memória, `project` é opcional. Quando omitido, o DecisionsSearch
usa o nome da raiz Git (ou da pasta atual, se não for um repositório Git) como
partição do projeto. As novas memórias recebem esse valor, e
`memory.query`/`memory.find_duplicates` filtram Qdrant e Neo4j por ele antes do
ranqueamento híbrido e da fusão RRF. Configure `DECISIONSSEARCH_PROJECT` quando
o servidor for iniciado fora da pasta do projeto ou quando o deploy precisar de
uma partição explícita.

Essa é uma partição lógica de memória, não uma barreira de autenticação. A ordem
de resolução é:

1. `DECISIONSSEARCH_PROJECT`, quando configurado;
2. o argumento `project` explícito, útil para importações e jobs em lote;
3. o nome da raiz do repositório Git;
4. o nome da pasta atual quando não existe uma raiz Git.

O fluxo recomendado para agentes é omitir `project`. O valor resolvido é gravado
junto com a memória e enviado para todos os ramos de recuperação. A consulta
primeiro filtra o projeto no ledger canônico, no Qdrant e no Neo4j; só depois
executa recuperação densa, sparse e estrutural, fusão RRF e reranking opcional.

## Como a memória funciona

O DecisionsSearch não trata uma transcrição, um diff ou um embedding como memória
por si só. Memória é conhecimento durável, tipado, associado a um projeto,
evidência, contexto e motivo para continuar útil depois da task atual.

```text
pasta de trabalho → tag do projeto → evento bruto → sanitização → extração
                 → gates de admissão → proposta/aprovação → ledger canônico
                 → outbox → projeção de busca no Qdrant
```

O caminho de escrita é seletivo de propósito:

- `memory.ingest_raw` guarda a fonte sanitizada na landing zone e pede ao
  extrator candidatos tipados;
- a cadeia de admissão exige projeto e evidência, verifica duplicidade ou
  refinamento, valida o contexto específico da categoria e calcula o peso;
- com o ledger canônico habilitado, o agente cria uma proposta com preview antes/
  depois, diff por campo, evidências e `preview_hash`;
- um operador ou uma política confiável aprova a proposta; o apply usa heads
  esperados (CAS) e cria revisão imutável, head, lineage e evento de outbox;
- o materializador publica o head ativo no Qdrant de forma idempotente. Qdrant é
  índice derivado de recuperação, nunca a fonte de verdade.

O modelo canônico separa identidade de conteúdo: `MemoryFamily` é a memória
lógica estável, `MemoryRevision` é uma versão imutável e `MemoryHead` aponta para
a versão publicada de um escopo e branch. Evidências, aliases, relações, janelas
de validade e auditoria continuam consultáveis. Atualizar título ou resumo cria
uma nova revisão, sem apagar silenciosamente o histórico.

Na leitura, o projeto resolvido é aplicado antes da geração de candidatos.
Embeddings densos encontram similaridade semântica, a busca sparse preserva
termos técnicos exatos e o grafo adiciona contexto estrutural. Essas listas são
combinadas por RRF; ativação espalhada, score composto e reranking podem refinar
os candidatos depois. Um score alto é sinal de relevância, não prova de que uma
afirmação seja verdadeira.

Para o ciclo completo, o modelo de dados, o isolamento por projeto e os limites
operacionais, veja o [relatório técnico da memória](docs-public/relatorio_memoria.md),
[`ARCHITECTURE.md`](ARCHITECTURE.md) e o [relatório público de resultados](docs-public/relatorio_resultados.md).

### Documentos públicos

- [`docs-public/instalacao.md`](docs-public/instalacao.md) — instalação e operação suportadas;
- [`docs-public/relatorio_memoria.md`](docs-public/relatorio_memoria.md) — ciclo da memória e partição por projeto;
- [`docs-public/relatorio_resultados.md`](docs-public/relatorio_resultados.md) — evidências reproduzíveis e limites atuais;
- [`docs-public/instalacao.pdf`](docs-public/instalacao.pdf) e [`docs-public/relatorio_resultados.pdf`](docs-public/relatorio_resultados.pdf) — versões visuais em PDF.

## Usando o DecisionsSearch no Dia a Dia: a Suíte de Skills

Conectar o servidor MCP dá ao seu agente 40+ tools brutas (`memory.query`, `memory.pr.create`, `graph.project.create`, ...) — poderosas, mas não algo que você quer chamar manualmente toda hora. `skills-memory/` traz uma suíte de 13 skills de agente que envolvem essas tools num fluxo de trabalho:

| Etapa | Skill | O que faz |
|-------|-------|-----------|
| 1. Setup (1x por projeto) | `decisionssearch-init` | Q&A sobre seu negócio/domínio → escreve `.decisionssearch/{business,architecture,code-patterns}.md`, instala as outras 12 skills no projeto, registra o nó do projeto no grafo |
| 2. Fim de cada PR | `decisionssearch-capture` | Uma varredura da sessão + diff do PR → detecta o que vale a pena lembrar (regra? decisão? padrão?) → cria os nós de memória certos, com sua confirmação, e os linka |
| 3. A qualquer momento | `query-memory` | "Já fizemos algo assim antes?" — busca semântica em PRs, regras, decisões, padrões e episódios de tasks passadas |
| 3. A qualquer momento | `rule-blame` / `architecture-blame` / `code-blame` | "Como isso chegou aqui?" — percorre a cadeia de PRs, decisões e versões substituídas de uma regra, uma escolha arquitetural ou um arquivo |
| 4. Periodicamente | `decisionssearch-update` | Sincroniza os `.decisionssearch/*.md` com o que o grafo aprendeu desde a última sincronização — propõe um diff, você aprova |

Instale com `decisionssearch-init` num projeto novo; a suíte tem seu próprio README, um template canônico que toda skill segue, e um arquivo de golden-set por skill (mais um teste consolidado de roteamento cruzado) — veja [`skills-memory/README.md`](skills-memory/README.md).

## Modos de Uso

### Modo 1: Memória Pessoal (Local)

Rode o DecisionsSearch localmente. Seu agente de IA conecta via MCP stdio ou HTTP (veja acima).

O servidor local usa a mesma composição full do servidor compartilhado. Para uma
regressão reproduzível sem infraestrutura, use o backend local explícito do
benchmark, sem tratar JSONL como memória canônica.

```yaml
# config/decisionssearch.yaml
mode: full
data_dir: data
```

O modo full (Neo4j + Qdrant) oferece travessia de grafo e consultas híbridas
vetor+estrutura.

### Modo 2: Memória Compartilhada do Time (Servidor)

Rode o DecisionsSearch num servidor. Os agentes de todo o time leem/escrevem na mesma base de conhecimento.

```bash
# No seu servidor
uv run decisionssearch --host 0.0.0.0 --port 8000
```

Os membros do time apontam seus agentes para o endpoint MCP compartilhado:

```json
{
  "mcpServers": {
    "decisionssearch": { "url": "https://your-domain.example/mcp" }
  }
}
```

As sessões de agente de todo mundo contribuem memórias. O job de varredura diária ingere automaticamente PRs e cards do GitHub, construindo um grafo de conhecimento compartilhado do histórico de decisões, padrões e arquitetura do time.

### Modo 3: Investigador Autônomo de Erros

Configure em `config/decisionssearch.yaml`:

```yaml
agent:
  provider: codex          # opencode | codex | claude
  timeout: 600
  codex:
    model: gpt-4o
    api_key: ${OPENAI_API_KEY}

safety:
  min_confidence: 0.7
  max_auto_fixes_per_hour: 3
  blocked_paths:
    - auth/
    - security/
    - .env

notifications:
  slack:
    enabled: true
    webhook_url: ${SLACK_WEBHOOK_URL}
```

Aponte seu pipeline de CI/CD para enviar erros:

```bash
# Exemplo com GitHub Actions
curl -X POST https://your-domain.example/api/webhook/errors \
  -H "Content-Type: application/json" \
  -H "X-Signature: $(echo -n "$body" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET")" \
  -d '{
    "error_type": "RuntimeError",
    "error_message": "Null pointer in UserService",
    "stack_trace": "at UserService.java:42\nat Controller.java:15",
    "service": "api",
    "environment": "production"
  }'
```

O DecisionsSearch vai:
1. Ingerir o erro e encontrar quais arquivos são afetados
2. Buscar PRs que mudaram esses arquivos recentemente (suspeitos)
3. Rodar um agente de código para investigar a causa-raiz
4. Se a confiança for alta o suficiente, criar um PR de correção
5. Notificar o time via Slack

## Categorias de Memória

Todo nó de memória tem uma `category` que determina quais campos são obrigatórios e validados por gates de admissão antes de entrar no grafo:

| Categoria | Criada via | Obrigatório além do básico | Use para |
|-----------|-------------|------------------------------|----------|
| `PRMemory` | `memory.pr.create` | `pr_url`, `work_item_url` | O que um PR mudou e por quê |
| `BusinessRule` | `memory.manual.create` | `domain` (não vazio) | Verdade de domínio durável que sobrevive a qualquer PR |
| `ArchitecturalDecision` | `memory.manual.create` | `architectural_rationale`, `alternatives_considered` | Uma escolha, sua motivação, trade-offs e alternativas rejeitadas |
| `DesignRule` | `memory.manual.create` | evidência e contexto durável | Convenção durável de código, estrutura ou interação |
| `DesignPattern` | `memory.manual.create` | evidência de reutilização | Solução recorrente de design ou interação |
| `CodePattern` | `memory.manual.create` | `examples` (não vazio) | Convenção reutilizável de implementação, com exemplo concreto |
| `FeatureDescription` | `memory.upsert` / extração | `objective`, `trigger` ou `related_files` | Como uma feature ou fluxo começa, funciona e termina |
| Episódio | `memory.episode.create` | `task_description`, `outcome` (`completed`/`failed`/`partial`) | O que foi tentado numa task específica e o que aconteceu — não é um `MemoryItem`, se conecta via `related_memory_ids` |
| Procedimento | `memory.procedure.create` | `steps` | Um runbook repetível para um tipo de task |

Relações entre `MemoryItem`s passam por duas APIs distintas e validadas — não misture:
- **PR → memória** (`memory.pr.link_memory`): `IMPLEMENTS`, `EVIDENCES`, `MODIFIES`.
- **memória → memória** (`memory.link`): `RELATED_TO`, `DEPENDS_ON`, `REFINES`, `DEPRECATES`, `CONFLICTS_WITH`, `EVOLVES_FROM`.

Substituir uma regra ou decisão é `memory.deprecate(memory_id, replaced_by, rationale)`, não um link manual — ele propõe `(nova)-[:DEPRECATES]->(antiga)` e só aplica após aprovação de operador.

## Tools MCP

O servidor expõe 40+ tools MCP. Categorias principais:

| Categoria | Tools | Descrição |
|-----------|-------|-----------|
| **Memória** | `memory.ingest_raw`, `memory.query`, `memory.get`, `memory.upsert`, `memory.manual.create`, `memory.find_duplicates` | Ingestão e recuperação com partição automática pela pasta do projeto. `memory.query`/`memory.upsert`/`memory.ingest_raw` aceitam `branch` opcional; `memory.find_duplicates` checa similaridade antes de criar |
| **Relações** | `memory.link`, `memory.deprecate` | Relacionamentos tipados entre memórias |
| **Reasoning** | `memory.reasoning.capture`, `memory.reasoning.similar` | Captura plano/raciocínio/decisões da task; recupera como tasks parecidas foram resolvidas e por quê |
| **Git Blame** | `memory.rule.history`, `memory.code.blame` | Timeline de versões de regra de negócio com PRs linkados; arquivo → PR → razão → regra/decisão |
| **Contexto** | `memory.context`, `memory.reflect`, `memory.capture_commit` | Carregamento pré-task, extração pós-task e verificação pós-commit |
| **Memória de PR** | `memory.pr.create`, `memory.pr.query`, `memory.pr.link_memory`, `memory.pr.linked_memories`, `memory.linked_prs` | Ligação PR↔memória |
| **Catálogo** | `graph.project.*`, `graph.category.*`, `graph.domain.*`, `graph.relation.*` | Gestão do catálogo do grafo |
| **Episódica** | `memory.episode.create`, `memory.episode.query` | Memórias de resultado de task |
| **Procedural** | `memory.procedure.create`, `memory.procedure.query` | Procedimentos reutilizáveis |
| **Erros** | `errors.ingest`, `errors.list`, `errors.get_investigation` | Pipeline de erros |
| **Sistema** | `system.jobs.list`, `system.jobs.run`, `system.jobs.history` | Controle do agendador |
| **Admin** | `memory.consolidate`, `memory.reconcile`, `memory.feedback` | Manutenção |

## Referência de Configuração

Toda config em `config/decisionssearch.yaml`. Variáveis de ambiente via sintaxe `${VAR:default}`.

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `mode` | `full` | `full` (Neo4j + Qdrant); `light` é rótulo legado de compatibilidade, não servidor somente JSONL |
| `LLM_PROVIDER` | `gemini` | Provedor de LLM: openai, zai, openrouter, gemini |
| `LLM_API_KEY` | — | Chave de API genérica para todos os provedores |
| `EMBEDDING_PROVIDER` | herda `LLM_PROVIDER` | Provedor separado opcional para embeddings, incluindo openrouter |
| `OPENROUTER_API_KEY` | — | Chave OpenRouter para chat, embeddings, reranking e worker autônomo |
| `OPENROUTER_RERANK_MODEL` | `qwen/qwen3-reranker-8b` | Modelo nativo de reranking do OpenRouter |
| `OPENROUTER_RERANK_ZDR` | `true` | Restringe o reranking a endpoints Zero Data Retention |
| `OPENROUTER_EMBEDDING_ZDR` | `true` | Restringe embeddings OpenRouter a endpoints ZDR |
| `DECISIONSSEARCH_LEDGER_BACKEND` | `neo4j` | Adapter canônico do ledger; `memory` é restrito a testes/regressões |
| `DECISIONSSEARCH_ENABLE_OPERATOR_TOOLS` | `false` | Habilita explicitamente as tools MCP de aprovação/rejeição/apply |
| `DECISIONSSEARCH_PROJECT` | não definido | Override opcional da partição quando o processo está fora do workspace |
| `NEO4J_URI` | `bolt://localhost:7687` | Conexão com o Neo4j |
| `NEO4J_PASSWORD` | — | Senha do Neo4j |
| `QDRANT_HOST` | `localhost` | Host do Qdrant |
| `QDRANT_PORT` | `6333` | Porta do Qdrant |
| `SPARSE_SEARCH_ENABLED` | `false` | Habilita recuperação BM25 sparse junto dos vetores densos em uma collection compatível |
| `RERANKER_PROVIDER` | `none` | none, cohere, jina, cross-encoder, openrouter, openai |

Veja `config/decisionssearch.yaml.example` para a referência completa com todas as opções.

## Arquitetura

O código da aplicação fica diretamente em `src/` (`src/domain`,
`src/application`, `src/infrastructure`, `src/interfaces` e `src/bootstrap`). O
empacotamento mapeia essa estrutura física para o namespace público estável
`decisionssearch.*`.

Veja [ARCHITECTURE.md](./ARCHITECTURE.md) para documentação técnica detalhada com diagramas cobrindo:
- Pipeline de ingestão de memória (admissão de 5 gates)
- Resolução do projeto e filtragem antes da busca
- Ledger canônico, aprovação, revisão e ciclo do outbox
- Pipeline de busca híbrida (fusão RRF + spreading activation)
- Fluxo de investigação de erros (agent worker + guardrails de segurança)
- Modelo de dados do grafo
- Topologias de deploy

Veja também [LIMITATIONS.md](./LIMITATIONS.md) para as limitações atuais da
implementação, suas evidências e o caminho proposto para resolvê-las.

## Captura de memória pós-commit

O hook versionado `.githooks/post-commit` reúne o `HEAD`, os arquivos alterados,
o PR aberto da branch (quando o `gh` estiver disponível) e a sessão indicada por
`DECISIONSSEARCH_SESSION_FILE` ou `.decisionssearch/session.md`. Ele envia esse contexto ao
LLM com a instrução de verificar conhecimento durável antes de criar memória.
`no_memory` é uma resposta válida: nenhuma alteração trivial vira memória por
força. Candidatos aceitos passam pelos gates de admissão e a captura é
idempotente por commit + PR + sessão.

Instale o hook uma vez na raiz do repositório:

```bash
uv run python -m scripts.install_git_hooks
```

O hook roda em background e é fail-open, portanto uma falha de OpenRouter,
GitHub, Qdrant ou Neo4j não bloqueia o commit. Para testar de forma síncrona:

```bash
DECISIONSSEARCH_COMMIT_MEMORY_HOOK_SYNC=1 \
DECISIONSSEARCH_SESSION_FILE=.decisionssearch/session.md \
git commit -m "minha alteração"
```

Agentes que já possuem o contexto podem chamar `memory.capture_commit` e enviar
explicitamente `session_context`, `commit_sha` e os metadados do PR. O comando
direto para diagnóstico é `uv run python -m scripts.post_commit_memory_hook
--repo . --dry-run`.

## Desenvolvimento

```bash
# Instala dependências de dev
uv sync --group dev

# Roda os testes
uv run pytest tests/ -q --ignore=tests/e2e

# Lint
uv run ruff check .

# Testes E2E (requer infraestrutura rodando)
RUN_E2E=1 uv run pytest tests/e2e -q
```

## Licença

MIT
