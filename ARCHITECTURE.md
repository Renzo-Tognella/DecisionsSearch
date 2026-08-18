# DecisionsSearch — Arquitetura

> Documento da arquitetura implementada no repositório. Quando uma capacidade
> ainda depende de validação de produção, ela aparece como parcial ou planejada;
> este documento não trata intenção futura como comportamento já garantido.

## 1. Finalidade e fronteiras

O DecisionsSearch é uma camada de memória persistente para agentes de desenvolvimento.
Ele recebe eventos, decisões, regras, padrões, procedimentos, episódios e
histórico de pull requests; transforma candidatos em conhecimento versionado; e
oferece busca híbrida por MCP e HTTP.

O objetivo arquitetural é que o conhecimento semântico tenha uma fonte canônica
com identidade estável, revisão, evidência, validade temporal, linhagem e
auditoria. `Neo4jMemoryLedger` é o adapter canônico selecionado por padrão pelo
container de produção. O `InMemoryMemoryLedger` só é selecionado explicitamente
para testes e regressões locais; ele não é uma promessa de durabilidade de
produção. Qdrant é uma projeção derivada para recuperação; nunca é a autoridade
da memória.

O investigador de erros é uma capacidade relacionada, mas ainda incompleta. Ele
faz triagem, encontra PRs suspeitos e pode chamar workers de agente; ainda não há
um contrato único, validado e seguro para todo o ciclo workspace → patch →
testes → PR.

## 2. Princípios invariantes

- **A fonte bruta não é conhecimento canônico.** Eventos entram na landing zone,
  passam por sanitização, extração e admissão antes de poderem virar proposta.
- **A identidade é estável.** Uma `MemoryFamily` representa a entidade lógica;
  título e texto podem mudar sem criar uma memória nova por acidente.
- **Revisões não são sobrescritas.** Cada publicação produz uma
  `MemoryRevision`, com hash, autor, motivo, pais, evidências e janela de
  validade.
- **O estado atual é derivado do head.** Um `MemoryHead` seleciona a revisão
  publicada para uma família, escopo e branch. O histórico permanece consultável.
- **Evidência é uma entidade.** Uma afirmação deve carregar origem, locator ou
  hash, postura (`supports`, `contradicts` ou `context`) e estado de verificação.
- **Agente propõe; operador ou política aprova.** O caminho semântico é
  `proposal → preview/diff → approval → CAS apply`; o agente não pode aprovar nem
  aplicar a própria proposta.
- **Qdrant é derivado.** O ledger grava o evento de outbox na mesma transação da
  publicação; o materializador atualiza o vetor de forma idempotente e pode ser
  reexecutado.
- **Concorrência é explícita.** A proposta carrega os heads esperados; se outro
  escritor publicar antes do apply, o CAS falha e a proposta precisa ser revista.
- **Contradição não é apagamento.** Invalidação, supersessão, conflito e merge
  preservam as versões anteriores e registram transições e linhagem.
- **O domínio não conhece adaptadores.** Regras, modelos e comandos ficam em
  `domain`; Neo4j, Qdrant, LLMs e GitHub ficam em `infrastructure`.

### Partição por projeto

Toda memória semântica pertence a uma partição lógica `project`. Quando o
caller omite esse campo, `project_context.resolve_project()` resolve o valor na
seguinte ordem: `DECISIONSSEARCH_PROJECT`, argumento explícito para workflows de
importação/lote, nome da raiz Git e, por fim, nome da pasta atual. A resolução
acontece no momento da operação, para que um processo MCP de longa duração não
reutilize o projeto de uma sessão anterior.

O valor resolvido é gravado no candidato, na proposta, na revisão do ledger, no
payload do Qdrant e nos registros do grafo. A busca resolve o projeto uma vez no
início e o envia aos ramos denso, sparse, estrutural e de ativação espalhada. Os
backends filtram por esse valor antes de devolver candidatos; o serviço híbrido
aplica ainda uma verificação exata na fronteira do RRF para impedir que um
payload sem filtro ou stale atravesse a partição.

Essa separação é um escopo lógico de recuperação, não uma fronteira de
autenticação ou autorização. Deploys compartilhados devem combinar a partição
com autenticação, autorização e política de operador.

### Perfil operacional validado

O perfil remoto usado na avaliação mais recente foi separado do código de
domínio e pode ser trocado por ambiente:

| Capacidade | Provider/modelo | Política |
|---|---|---|
| Chat e extração | OpenRouter / `openai/gpt-4o-mini` | OpenAI-compatible; a política de retenção deve ser configurada no provider da conta ou da requisição. |
| Embeddings densos | OpenRouter / `openai/text-embedding-3-small` | 512 dimensões; a integração envia `provider.zdr=true` quando `OPENROUTER_EMBEDDING_ZDR=true`. |
| Reranking | OpenRouter `/api/v1/rerank` / `qwen/qwen3-reranker-8b` | `OPENROUTER_RERANK_ZDR=true`; retorno é uma ordenação por índice e score. |

Esse perfil não transforma o provider em fonte de verdade: a chave, a resposta
do modelo e o score continuam sendo infraestrutura não confiável. Trocar o
modelo ou a dimensão do embedding exige reindexação controlada da coleção
Qdrant. O modelo Qwen foi escolhido por estar disponível no catálogo de
endpoints ZDR do OpenRouter; a aplicação também mantém providers alternativos
para ambientes sem essa configuração.

Há dois contextos de execução que não devem ser confundidos:

- **Servidor HTTP/MCP:** `create_container()` usa Neo4j por padrão, bloqueia
  escritas semânticas legadas e materializa heads no Qdrant.
- **Regressão local/benchmark:** o harness declara backend local, usa
  `InMemoryMemoryLedger` e persiste snapshots por `run_id`; esse caminho mede
  contratos e qualidade, não durabilidade de produção.

## 3. Visão de contexto

~~~mermaid
flowchart LR
    agent["Agente de código"]
    team["Operador e equipe"]
    webhook["Webhook de CI/CD"]

    asgi["ASGI\ndecisionssearch"]
    mcp["MCP\nstdio ou /mcp"]
    http["HTTP API\n/api"]
    bootstrap["Composition root\nbootstrap/container.py"]
    app["Casos de uso\napplication"]
    domain["Regras e modelos\ndomain"]
    ledger["Ledger canônico\nNeo4j ou InMemory explícito"]
    outbox["Outbox\nidempotente"]
    neo4j[("Neo4j\nledger + grafo")]
    qdrant[("Qdrant\nprojeção de busca")]
    jsonl[("JSONL\nlanding zone + snapshot local")]
    providers["OpenRouter/LLMs\nembeddings/rerankers\nGitHub e notificações"]

    agent --> mcp
    team --> http
    webhook --> http
    asgi --> mcp
    asgi --> http
    mcp --> bootstrap
    http --> bootstrap
    bootstrap --> app
    app --> domain
    app --> ledger
    ledger --> outbox
    ledger --> neo4j
    outbox --> qdrant
    app --> jsonl
    app --> providers
~~~

No ambiente de produção, `Neo4jMemoryLedger` é o adapter canônico persistente.
Em testes e no benchmark local, o container escolhe explicitamente
`InMemoryMemoryLedger` e persiste um snapshot para reproduzir a regressão. Não
existe fallback silencioso entre esses contratos.

## 4. Camadas físicas

O código da aplicação fica diretamente em `src/`, sem um diretório físico
intermediário `src/decisionssearch/`:

```text
src/
├── application/
├── bootstrap/
├── domain/
├── infrastructure/
└── interfaces/
```

O nome lógico do pacote continua sendo `decisionssearch`. O mapeamento declarado no
`pyproject.toml` faz, por exemplo, `src/domain` ser distribuído e importado como
`decisionssearch.domain`. Assim, a organização física é mais direta sem alterar a API
Python nem os entry points existentes.

~~~mermaid
flowchart TB
    interfaces["interfaces\nMCP e HTTP"] --> bootstrap["bootstrap\ncomposição"]
    bootstrap --> application["application\ncasos de uso"]
    application --> domain["domain\nregras e modelos"]
    application --> ports["application/ports\ncontratos"]
    infrastructure["infrastructure\nadapters externos"] --> domain
    infrastructure --> ports
    bootstrap --> infrastructure
~~~

### `domain`

Contém modelos Pydantic, enums, validações, comandos e exceções de negócio.

- `domain/memory`: `MemoryItem`, `MemoryCandidate` e `RawEvent`, mantidos como
  modelos de entrada e compatibilidade;
- `domain/memory_ledger`: `MemoryFamily`, `MemoryRevision`, `MemoryHead`,
  `Evidence`, `ChangeProposal`, `ApprovalDecision`, `RevisionTransition`,
  `RelationAssertion` e `OutboxEvent`;
- `domain/pr_memory`: registro operacional de pull requests;
- `domain/catalog`: projetos, categorias, domínios e módulos;
- `domain/episodic`, `domain/procedural` e `domain/incidents`: episódios,
  procedimentos e incidentes;
- `domain/shared`: branches, status, envelopes e exceções compartilhadas.

O domínio não importa `application`, `infrastructure` ou `interfaces`. Essa
invariante é verificada por `tests/unit/test_architecture_boundaries.py`.

### `application`

Coordena casos de uso e políticas:

- `memory/ledger`: serviços de proposta, aprovação, apply, consulta, migração,
  snapshot e materialização do outbox;
- `memory`: ingestão, sanitização, extração, admissão, autoria manual,
  consolidação, memória episódica/procedural e hooks de commit;
- `search`: busca híbrida, RRF, HyDE, reescrita, ativação espalhada, score,
  cache, reranking e síntese;
- `pr_memory`: criação, consulta, relacionamento e descoberta de PRs;
- `agents`: loop de agente e reflexão cognitiva;
- `error_investigation`: ingestão e orquestração de investigação;
- `governance`, `jobs` e `notifications`: pesos, auditoria, telemetria,
  scheduler e notificações;
- `ports`: interfaces para embeddings, vetor, grafo, reranking e gates.

Alguns serviços ainda recebem classes concretas para manter compatibilidade com
o sistema existente; a inversão completa de dependências é uma melhoria
conhecida, não uma propriedade já concluída.

### `infrastructure`

Implementa detalhes externos:

- `persistence/neo4j/neo4j_memory_ledger.py`: adapter do ledger, transações,
  CAS, constraints, heads, relações, transições e outbox;
- `persistence/neo4j/neo4j_service.py`: catálogo, PRs e compatibilidade legada;
- `persistence/qdrant/qdrant_service.py`: projeção vetorial e filtros;
- `ai/embeddings`, `ai/providers` e `ai/reranking`: modelos e recuperação;
- `agents`: workers OpenCode e outros providers;
- `integrations`: GitHub, Slack e webhooks;
- `config`: YAML, defaults e variáveis de ambiente.

### `interfaces`

São os adapters de entrada:

- `interfaces/mcp/main.py` cria o servidor MCP;
- `interfaces/mcp/tools.py` registra consultas, propostas, rollback e demais
  ferramentas; ferramentas de aprovação/rejeição/apply ficam em um registro de
  operador opcional;
- `interfaces/http/asgi.py` e `http_app.py` compõem ASGI/FastAPI;
- `interfaces/http/routes/memory_routes.py` expõe proposta, aprovação, rejeição,
  aplicação, consulta e histórico;
- `interfaces/http/routes` também contém catálogo, PR e webhook de erro;
- `interfaces/http/schemas` valida contratos HTTP.

### `bootstrap`

`bootstrap/container.py` é o composition root. `create_container()` resolve
`DECISIONSSEARCH_LEDGER_BACKEND` (`neo4j` por padrão; `memory` somente para testes),
conecta `ProposalService`, `LocalApprovalBoundary`, `LedgerApplyService`,
`QdrantHeadMaterializer`, busca e providers. No container de produção, escritas
semânticas legadas de Neo4j/Qdrant são bloqueadas; o fluxo canônico é
obrigatório. `wire_error_pipeline()` é ligado pela composição ASGI e adiciona
investigação, worker, notificações, GitHub e scheduler depois que o container
base foi criado.

## 5. Ledger canônico de memória

### Entidades

| Entidade | Responsabilidade |
|---|---|
| `MemoryFamily` | Identidade lógica estável, escopo, branch e estado da família. |
| `MemoryRevision` | Snapshot imutável do conteúdo, hash, autor, pais e validade. |
| `MemoryHead` | Revisão publicada para uma família/escopo/branch. |
| `MemoryAlias` | Compatibilidade com IDs legados e redirecionamentos após merge. |
| `Evidence` | Fonte, locator, trecho/hash, extractor e verificação. |
| `RevisionEvidence` | Vínculo entre revisão e evidência, com stance e confiança. |
| `ChangeProposal` | Intenção de alteração, antes/depois, diff, heads esperados e preview hash. |
| `ApprovalDecision` | Decisão de operador/política; agentes são rejeitados como aprovadores. |
| `RevisionTransition` | Supersessão, invalidação, archive, rollback ou merge. |
| `RelationAssertion` | Relação tipada entre famílias com origem, validade e estado. |
| `OutboxEvent` | Publicação para materializadores, com status, retry e dead-letter. |

O `memory_id` legado é um alias estável derivado da família. Atualizar título,
resumo ou campos não muda a identidade lógica nem cria um novo ID de busca.

### Fluxo de escrita

~~~mermaid
flowchart LR
    candidate["Candidate\nou comando"] --> proposal["ChangeProposal"]
    proposal --> preview["Preview\ndiff + evidência"]
    preview --> approval{"Aprovação\nde operador/política"}
    approval -->|rejeita| audit["Decisão auditada"]
    approval -->|aprova| cas["Apply com\nexpected heads"]
    cas --> revision["Revision + head\nna mesma transação"]
    revision --> outbox["Outbox"]
    outbox --> materializer["Materializer"]
    materializer --> qdrant["Qdrant derivado"]
~~~

Regras do fluxo:

1. a proposta é idempotente por chave de origem e operação;
2. `preview_hash` impede aplicar um preview alterado;
3. `expected_heads` implementa compare-and-swap;
4. somente uma decisão de aprovação válida pode ser consumida pelo apply;
5. o apply não aceita principal agente, anônimo ou sistema como aprovador;
6. revisão, head, transição, relação e outbox são gravados atomicamente pelo
   adapter persistente;
7. a projeção vetorial pode atrasar, mas o atraso aparece no estado do outbox.

### Operações de ciclo de vida

- **Create:** cria família, revisão inicial, head, alias, evidência e outbox.
- **Update:** cria revisão filha e supersede o head anterior somente se o CAS
  ainda corresponder à prévia.
- **Invalidate/expire:** encerra a validade ou muda o estado com motivo; não
  remove o histórico.
- **Rollback:** cria revisão que aponta para uma revisão anterior; o rollback
  também é proposta e aprovação, não mutação destrutiva.
- **Merge:** exige duas ou mais famílias e heads esperados, cria revisão com
  múltiplos pais, registra `MERGED_INTO`, redireciona aliases e aposenta as
  famílias de origem.
- **Create-and-link/refine:** quando a admissão classifica um candidato como
  refinamento, cria uma família nova e registra `REFINES` da nova revisão para o
  head alvo na mesma aplicação transacional; não há fallback silencioso para
  `CREATE`.
- **Link:** cria `RelationAssertion` tipada e governada; `RELATED_TO` é
  armazenado uma única vez em ordem canônica e percorrido nos dois sentidos.
  Uma aresta não é tratada como fato sem origem, head congelado, evidência e
  estado.
- **Deprecate:** invalida/supersede a memória antiga e, quando há substituta,
  registra `DEPRECATES` no sentido `substituta -> antiga`, com CAS dos dois
  heads.

O merge atual faz recombinação determinística de campos e registra `FieldOrigin`.
Uma estratégia parecida com crossover genético pode gerar propostas no futuro,
mas não substitui evidência, explicação nem revisão humana diante de conflito.

## 6. Armazenamento e projeções

### Neo4j / `Neo4jMemoryLedger`

No caminho canônico persistente, Neo4j guarda famílias, revisões, heads,
aliases, evidências, propostas, aprovações, transições, relações e outbox. O
adapter cria constraints/indexes e executa o CAS dentro de transações.

`PRMemory`, `Project`, `Category`, `Domain`, `Module`, `Error`, `File` e
`Investigation` continuam sendo modelos operacionais do sistema. Eles podem
fornecer evidência ou contexto, mas não substituem o ledger de memória
semântica.

Relações estruturais do catálogo/PR e relações semânticas governadas pelo ledger
devem ser distinguidas. A compatibilidade com `MemoryItem` é uma projeção de
leitura, não outra fonte de verdade.

### Qdrant

Qdrant contém somente heads materializados. O ponto usa identidade estável da
família combinada ao escopo/branch; o payload inclui família, revisão, hash,
categoria, projeto e janela de validade.

- vetor denso: similaridade semântica;
- vetor sparse nomeado: busca lexical quando habilitado;
- filtros: projeto resolvido, categoria, branch, estado e validade;
- materialização: upsert/delete idempotente, verificação de revisão atual e
  retry/dead-letter.

No backend Qdrant local, filtros temporais com limites nulos podem não ser
avaliados pelo motor. Quando a consulta filtrada retorna vazia, o adapter faz
fallback para os filtros estruturais e aplica `valid_from`/`valid_to` em Python;
isso preserva a semântica do benchmark, mas ainda precisa de contract test no
Qdrant servidor.

Uma leitura nunca deve promover um ponto Qdrant que não corresponda a um head
canônico ativo. O rebuild deve conseguir recriar a coleção a partir do ledger.

### JSONL e snapshots

JSONL é usado para landing zone, auditoria local, estado idempotente e snapshots
do backend local. Ele não substitui o ledger persistente. O benchmark registra o
backend, o adapter, a contagem de revisões/heads, o estado do outbox e o hash dos
artefatos no `evaluation_manifest.json`.

## 7. Fluxo de ingestão e consolidação

~~~mermaid
flowchart LR
    raw["RawEvent"] --> sanitize["Sanitização"]
    sanitize --> extract["Extração"]
    extract --> gates["Admission gates"]
    gates --> candidate["Candidate"]
    candidate --> proposal["ProposalService"]
    proposal --> approval["Approval boundary"]
    approval --> ledger["Ledger apply"]
~~~

1. `RawEvent` preserva a entrada antes da classificação.
2. `ExtractionService` produz candidatos tipados.
3. `AdmissionService` aplica projeto, evidência, duplicidade, contexto e peso;
   o projeto vem da pasta de trabalho quando o caller não informa um override.
4. No modo de ledger, persistência semântica termina em proposta; não cria um
   `MemoryItem` ativo fictício para fingir que a aprovação ocorreu.
5. Consolidação pode sugerir update, invalidação, expiração, merge e
   `RELATED_TO` por contexto compartilhado; ela não aprova a própria sugestão.
6. Episódios e telemetria continuam sendo fontes de sinal. Um sinal não vira
   automaticamente uma afirmação histórica.

## 8. Busca híbrida e temporal

`HybridSearchService` resolve a partição `project` antes de recuperar qualquer
candidato. Depois combina query rewriting, HyDE opcional, embedding denso,
embedding sparse, Qdrant, candidatos estruturais, ativação espalhada, RRF, score
composto e reranking.

Quando o ledger está configurado:

1. o serviço resolve o projeto da operação e seleciona heads ativos por projeto,
   categoria, branch e janela de validade;
2. Qdrant fornece candidatos derivados já filtrados por projeto;
3. Neo4j/ledger fornecem os candidatos estruturais da mesma partição;
4. candidatos densos, sparse e estruturais sem o projeto exato são descartados
   antes do RRF;
5. a consulta estrutural e os resultados do ledger são reconciliados pela
   família/revisão/hash;
6. o resultado expõe a identidade estável, revisão, evidências e validade;
7. `query_at` consulta o estado observado no instante solicitado, sem confundir
   uma revisão antiga com o head atual;
8. score de relevância não é tratado como prova de veracidade; o sistema deve
   poder se abster quando a evidência não for suficiente.

Sem ledger, componentes legados permanecem disponíveis para compatibilidade e
testes. Eles não são o caminho de escrita semântica do container de produção.

## 9. Interfaces públicas

### Comandos

| Comando | Entry point | Uso |
|---|---|---|
| `decisionssearch` | `decisionssearch.interfaces.http.asgi:main` | HTTP + MCP via ASGI |
| `decisionssearch-mcp` | `decisionssearch.interfaces.mcp.main:main` | MCP via stdio |

### HTTP

- `GET /api/health`: health check;
- `/api/catalog/...`: projetos, categorias, domínios, relações e CSV;
- `/api/memories/manual`: proposta de autoria manual;
- `/api/memories/changes/{id}`: consulta e prévia de proposta;
- `/api/memories/changes/{id}/approve`: decisão de operador;
- `/api/memories/changes/{id}/reject`: rejeição auditada;
- `/api/memories/changes/{id}/apply`: aplicação de aprovação válida;
- `/api/memories`: consulta/histórico compatível;
- `/api/pr-memories`: criação e consulta de PRMemory;
- `POST /api/webhook/errors`: entrada autenticada de erros;
- `/mcp`: transporte MCP via HTTP.

As rotas de aprovação exigem principal de operador e conferem a identidade no
apply. A autenticação local por header é uma barreira de desenvolvimento, não
uma solução corporativa completa.

### MCP

As tools incluem memória, PRMemory, catálogo, episódios, procedimentos, erros,
jobs e sistema. A superfície de mudança expõe proposta, consulta e rollback ao
agente; aprovação, rejeição e apply ficam em `register_operator_tools()` e só
são habilitados quando `DECISIONSSEARCH_ENABLE_OPERATOR_TOOLS` está explicitamente
configurado.

`TOOL_SURFACE_VERSION` é `2.2`. Alterações de contrato devem atualizar os testes
MCP correspondentes e os shims deprecated.

## 10. Investigação de erros

O `ErrorInvestigationOrchestrator` executa atualmente:

1. recebe `ErrorEvent` por webhook ou tool;
2. agrupa o erro por fingerprint, serviço e ambiente;
3. relaciona stack frames a arquivos e PRs modificadores;
4. aplica circuit breaker, limites, caminhos bloqueados e política de confiança;
5. chama o worker configurado e registra findings;
6. pode notificar e, conforme configuração, iniciar integração com GitHub.

Isso ainda não equivale a um code agent completo. O caminho desejado é:

~~~text
erro → triagem → contexto do ledger → workspace descartável
     → ferramentas do code agent → patch proposto → testes
     → aprovação → commit/PR → feedback → memória versionada
~~~

Antes de habilitar auto-fix de produção, falta um `CodeAgentBackend` comum com
capacidades declaradas, sandbox, permissões mínimas, limite de custo/tempo,
diff, testes reproduzíveis e prova de que o PR corresponde ao diagnóstico.

## 11. Inicialização e configuração

`create_container()` compõe ledger, proposta, aprovação, apply, materializador,
Neo4j, Qdrant, busca e providers. A composição ASGI chama também
`wire_error_pipeline()` para conectar GitHub, notificações e jobs. O caminho
típico do servidor é:

~~~bash
uv sync
cp .env.example .env
cp config/decisionssearch.yaml.example config/decisionssearch.yaml
docker compose up -d
uv run python -m scripts.bootstrap_qdrant
uv run decisionssearch
~~~

Para MCP via stdio:

~~~bash
uv run decisionssearch-mcp
~~~

O servidor atual é o caminho full: exige Neo4j e Qdrant, e o backend do ledger
deve ser declarado quando não for o padrão `neo4j`. O campo `mode` do YAML ainda
é metadado de configuração/compatibilidade; ele não troca o container HTTP/MCP
para uma implementação JSONL-only. JSONL continua sendo landing zone, auditoria
e snapshot local. O harness de benchmark tem seu próprio backend local explícito.
Nunca interpretar uma porta TCP aberta como prova de autenticação ou de
consistência do serviço.

## 12. Migração e operação

`LegacyMemoryMigrator` faz dry-run determinístico e, para cada registro legado,
planeja família, revisão `legacy_import`, evidência de origem e alias. IDs
ambíguos vão para quarentena. Se o legado só contém o estado atual, o migrador
não inventa revisões anteriores.

Antes do cutover persistente, a operação precisa executar:

1. backup do ledger, schema e outbox;
2. migração dry-run com contagens, checksums e manifest;
3. reindexação paralela do Qdrant;
4. reconciliação de famílias, heads, aliases e eventos;
5. plano de rollback e janela de observação;
6. leases de workers, métricas de lag e alertas de dead-letter.

Outbox e materializador já cobrem retry básico, idempotência local e claim/lease
com token de worker. Fencing entre processos, reconciliação distribuída, fault
injection e recuperação após queda ainda precisam de validação real.

## 13. Testes e evidências

Comandos principais:

~~~bash
uv run pytest tests/ -q --ignore=tests/e2e
uv run ruff check .
uv run python -m compileall -q src scripts tests
uv build
RUN_E2E=1 uv run pytest tests/e2e -q
~~~

Os testes do ledger local cobrem criação, update, histórico, diff, alias
estável, bloqueio de autoaprovação, CAS, rollback, merge, invalidação, relações,
migração, retry e lease do materializador. A execução atual registra 445 testes
automatizados aprovados e 1 teste ignorado, além de ingest, golden e evaluate em
backend local explícito. O benchmark remoto de referência usa 100 PRs, 79
candidatos/interações, embeddings OpenRouter e o reranker Qwen com ZDR; seus
resultados ficam nos artefatos do `run_id`, não neste documento como garantia de
produção.

O E2E requer Neo4j autenticado e Qdrant configurados. Se falhar por credenciais
ou serviço ausente, isso deve aparecer como bloqueio de infraestrutura; não é
permitido reportar o teste como aprovado nem converter automaticamente para
backend local.

O relatório público de avaliação deve sempre expor:

- backend solicitado e resolvido;
- store canônico e adapter;
- número de famílias, revisões, heads e relações;
- estado do outbox;
- origem dos dados e hash dos artefatos;
- health das dependências, incluindo configuração de autenticação;
- consultas, métricas, fallback e limitações do conjunto de avaliação.

## 14. Limites e critérios para a fonte única

O estado detalhado está em [`LIMITATIONS.md`](LIMITATIONS.md). Os bloqueios
principais para declarar uma fonte única de verdade em produção são:

1. validar `Neo4jMemoryLedger` e Qdrant reais com autenticação, concorrência e
   falhas;
2. concluir migração, backup, checksum, reindexação e rollback;
3. trocar o header local por autenticação/autorização forte e política de
   aprovadores;
4. definir suficiência, independência e conflito de evidências por domínio;
5. completar invalidação, obsolescência, branch, temporalidade e relações em
   todas as superfícies;
6. medir merge com casos rotulados e manter contradições explícitas;
7. adicionar abstention, explicabilidade e avaliação histórica independente;
8. fechar o contrato sandboxed do investigador de erros e do code agent.

Até esses critérios serem atendidos, a formulação correta é: **DecisionsSearch é um
sistema de memória versionada com ledger canônico protegido e regressão local
verificável; ainda não é uma autoridade histórica única em produção.**
