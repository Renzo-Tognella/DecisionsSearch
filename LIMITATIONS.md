# Limitações atuais do DecisionsSearch

Este documento descreve o estado real do projeto após a introdução do ledger de
memória versionada. O objetivo é deixar claro o que já pode ser usado, o que foi
validado apenas no backend local e o que ainda impede o DecisionsSearch de ser tratado
como a única fonte de verdade do conhecimento histórico.

## Conclusão curta

O projeto já pode ser utilizado como sistema de memória assistida: ele preserva
revisões imutáveis, evidencia, validade temporal, lineage, propostas de mudança,
aprovação separada, CAS e materialização derivada no Qdrant. Agentes não recebem
por padrão uma porta para aprovar ou aplicar alterações.

Ainda não é correto afirmar que ele é a fonte única de verdade em produção. O
principal motivo é operacional: a implementação canônica Neo4j existe, mas não
foi validada nesta máquina contra um Neo4j saudável; o benchmark reproduzido usa
explicitamente `InMemoryMemoryLedger` com snapshot local. Também falta completar
migração, autenticação forte da aprovação, políticas de obsolescência e o code
agent de investigação. O outbox já possui claim/lease e retry no caminho local;
o que ainda não foi provado é a operação distribuída, a reconciliação e a
recuperação diante de falhas reais.

## Estados usados neste documento

- **Implementado**: existe no caminho canônico e possui testes locais.
- **Parcial**: há implementação, mas falta validação real, integração completa ou
  uma política de produção.
- **Planejado**: a direção está definida, mas ainda não existe implementação
  suficiente para prometer a capacidade.
- **Sem decisão**: ainda não há uma escolha técnica segura.

Prioridade **P0** significa risco para integridade, proveniência ou automação;
**P1** limita a operação ou a qualidade; **P2** é evolução de escala e produto.

## Matriz de limitações

| ID | Prioridade | Estado | Limitação |
|---|---:|---|---|
| L1 | P0 | Parcial | O ledger versionado já existe, mas a validação do adapter Neo4j real e a migração de todo o legado ainda não foram concluídas. |
| L2 | P0 | Parcial | A barreira de proposta/aprovação/aplicação existe; autenticação, autorização e separação forte de operador ainda são locais. |
| L3 | P0 | Parcial | Evidências são entidades do ledger, mas a verificação de fonte, independência e políticas de confiança ainda são simples. |
| L4 | P0 | Parcial | Invalidação e validade temporal existem; descobrir automaticamente que uma regra ficou obsoleta continua sendo um problema de domínio. |
| L5 | P0 | Parcial | Merge preserva lineage e faz união determinística de campos; conflitos semânticos ainda não são resolvidos automaticamente. |
| L6 | P0 | Parcial | Outbox e materializador desacoplam Neo4j/Qdrant e já têm claim/lease local; fencing distribuído, reconciliação completa e teste real de falhas ainda faltam. |
| L7 | P1 | Parcial | Relações governadas existem para o ledger, mas descoberta, confiança e uso das relações na busca ainda são limitados. |
| L8 | P1 | Parcial | Histórico, validade e branch estão no modelo e em parte das consultas, mas não atravessam todas as APIs e operações legadas. |
| L9 | P1 | Parcial | A busca canônica lê heads do ledger, porém o ranking, a abstention e a qualidade de extração ainda dependem de calibração. |
| L10 | P0 | Planejado | O investigador de erros ainda não é um code agent com workspace, ferramentas, patch, testes e PR verificável. |
| L11 | P1 | Parcial | Há abstrações separadas para LLM, embedding e reranking, mas ainda não existe um contrato único de capacidades nem um adapter de SDK de code agent. |
| L12 | P1 | Parcial | Jobs, telemetria e operação multi-instância ainda são locais e não têm observabilidade durável completa. |
| L13 | P0 | Parcial | O benchmark local valida contratos do ledger, mas não prova consistência do Neo4j/Qdrant servidor nem o fluxo de produção. |
| L14 | P1 | Parcial | O backfill legado preserva o snapshot observado, mas não consegue reconstruir revisões históricas que nunca foram armazenadas. |

## L1 — O ledger ainda não é a verdade de produção em todos os ambientes

### O que já existe

O domínio separa:

- `MemoryFamily`: identidade lógica estável;
- `MemoryRevision`: snapshot imutável com hash, versão, pais, autor e motivo;
- `MemoryHead`: revisão atual por escopo e branch;
- `MemoryAlias`: compatibilidade de leitura com `memory_id` estável por família;
- `RevisionTransition`: histórico de supersessão, invalidação, archive e rollback.

O container de produção bloqueia as escritas semânticas legadas de Neo4j e as
escritas diretas legadas do Qdrant. O caminho esperado é proposta, aprovação,
aplicação CAS e outbox. A leitura semântica passa pelo ledger quando ele está
configurado.

### O que ainda limita a promessa

O adapter `Neo4jMemoryLedger` não foi exercitado nesta execução contra um Neo4j
saudável. O benchmark reproduzido usa um `InMemoryMemoryLedger` persistido em
`artifacts/public_repo_eval/runs/<run_id>/ledger_state.json`; isso é uma
regressão local explícita, não uma prova de durabilidade de produção.

### Como resolver

1. Subir Neo4j e Qdrant em ambiente efêmero de CI.
2. Rodar contract tests contra as versões reais dos drivers.
3. Fazer migração dry-run, backup, contagem e checksum antes do cutover.
4. Desabilitar permanentemente o caminho legado depois de comparar os heads e o
   outbox.

## L2 — Aprovação humana existe, mas ainda não é governança corporativa

Cada mutação semântica gera um `ChangeProposal` com `before`, `after`, diff por
campo, evidências, heads esperados e `preview_hash`. O `LocalApprovalBoundary`
recusa principal do tipo agente e o apply aceita apenas aprovação ainda não
consumida, com CAS e validade.

A API HTTP usa um principal de operador e as ferramentas de operador não são
registradas por padrão no MCP. O benchmark usa deliberadamente
`benchmark-operator` para testar o caminho completo; isso não equivale a uma
aprovação humana real.

### O que falta

- autenticação e autorização integradas a um provedor externo;
- política de dois aprovadores para categorias de alto impacto;
- registro imutável do motivo de rejeição e identidade auditável;
- expiração, revogação e revisão de permissões;
- interface de revisão que mostre antes/depois e lineage sem depender de JSON.

## L3 — Evidência é persistida, mas a epistemologia ainda é simples

`Evidence`, `RevisionEvidence` e hash do conteúdo agora fazem parte do ledger.
Uma revisão pode carregar fonte, locator, trecho/hash, confiabilidade, extractor,
modelo e stance. A migração legada marca a evidência como indisponível quando o
registro original não continha a fonte.

Isso resolve a perda completa de proveniência, mas não resolve automaticamente:

- se o link ainda existe;
- se a fonte é primária ou apenas uma cópia;
- se duas evidências são independentes;
- se um trecho contradiz uma regra mais recente;
- se o modelo inventou uma síntese não presente na fonte.

### Próximo passo

Criar verificadores por tipo de fonte, deduplicar por locator/hash, guardar
resultado de verificação e aplicar uma política de confiança por categoria. Uma
contagem de evidências nunca deve ser suficiente para promover ou fundir uma
memória de alto impacto.

## L4 — Obsolescência não pode ser inferida apenas por uso

O ledger possui estados `active`, `superseded`, `invalidated`, `conflicted` e
`archived`. Invalidação, supersessão e archive geram uma nova proposta/revisão,
registram motivo e deixam o snapshot anterior consultável. `valid_from` e
`valid_to` são considerados pela listagem de heads ativos, consulta histórica e
materializador.

A consolidação pode propor invalidação quando uma validade conhecida expirou.
Isso é diferente de concluir que uma regra deixou de ser verdadeira. Baixo uso,
decay de peso e feedback são apenas sinais.

### Política ainda necessária

Cada categoria deve ter política própria. Uma regra de negócio pode exigir fonte
oficial ou dono do domínio; uma decisão arquitetural pode exigir PR, ADR ou
mudança de schema; uma memória operacional pode expirar naturalmente. O sistema
ainda não possui esses responsáveis, SLAs e verificadores automatizados.

## L5 — Merge é lineage + proposta, não um algoritmo genético autônomo

O merge agora:

- exige pelo menos duas revisões e heads esperados de duas famílias;
- cria uma revisão alvo com múltiplos pais;
- registra `FieldOrigin` para campos recombinados;
- aposenta famílias de origem e redireciona aliases;
- registra relações `MERGED_INTO`;
- materializa o resultado somente após aprovação.

A consolidação atual faz uma união determinística de listas e preenche campos
vazios. Ela não sabe decidir que duas frases contraditórias são ambas verdadeiras
em contextos diferentes, nem gera uma síntese nova com garantia factual.

### Sobre algoritmos genéticos

A ideia de crossover pode ser útil como experimento, mas não deve ser a primeira
implementação. O caminho seguro é recombinação restrita por evidência: cada campo
precisa apontar para uma fonte, conflitos permanecem explícitos e o resultado é
uma proposta humana. Só depois de um conjunto de casos rotulados faria sentido
comparar seleção, crossover ou mutação estocástica com a estratégia determinística.

## L6 — O outbox reduz a inconsistência, mas ainda não é operação distribuída

A aplicação do ledger grava revisão, heads, transições, relações e evento de
outbox na mesma transação do adapter. O Qdrant é derivado: o materializador usa
identidade estável de head, verifica hash/estado/current head, reprocessa falhas e
envia eventos persistentes para dead-letter após tentativas.

Ainda faltam:

- backoff exponencial e re-agendamento explícito de falhas;
- métricas e alertas para dead-letter;
- reconciliação que detecta e repara divergência por checksum;
- rebuild completo validado contra Neo4j real;
- teste de queda exatamente entre commit canônico e materialização.

O claim/lease já está implementado nos adapters locais e Neo4j, com token de
worker e expiração. Isso evita que dois consumidores confirmem o mesmo evento
por acidente no mesmo ledger. Ainda faltam fencing verificável entre processos
para toda a cadeia de materialização, backoff, métricas de lag, alertas,
reconciliação por checksum e testes de queda exatamente entre commit canônico e
projeção. O snapshot em memória é útil para benchmark, mas não substitui
backup, WAL, replicação e política de recuperação.

## L7 — Relações são governadas, mas ainda pouco inteligentes

`RelationAssertion` tornou relações entre famílias objetos de primeira classe.
Links manuais, merges e lineage podem passar por proposta, evidência, estado e
revisões de origem/alvo. Isso evita que uma aresta sem contexto seja tratada como
verdade histórica.

A descoberta automática agora cobre dois casos controlados: `REFINES` é criado
quando a admissão encontra uma memória semanticamente próxima, e a consolidação
pode propor `RELATED_TO` quando há arquivo ou módulo compartilhado com contexto
compatível. Ambas as mudanças passam por proposta, aprovação, CAS e outbox;
`RELATED_TO` é uma aresta canônica simétrica e `DEPRECATES` aponta da substituta
para a memória antiga.

Ainda há limites: relações operacionais de PRMemory e projeções de
compatibilidade continuam existindo fora do grafo semântico; nem toda relação
legada possui confiança, validade e evidência equivalentes; e a consolidação não
infere sozinha `CONFLICTS_WITH`, `DEPENDS_ON` ou a verdade de uma obsolescência
sem evidência explícita. A busca também não usa todas as relações tipadas com
pesos e direção específicos.

### Próximo passo

Medir a precisão das sugestões `RELATED_TO`/`REFINES`, adicionar políticas
separadas para `CONFLICTS_WITH` e `DEPENDS_ON`, e distinguir contexto relacionado
de conhecimento que sustenta uma resposta.

## L8 — Temporalidade e branch estão melhores, mas não são universais

O modelo, heads, Qdrant payload e `memory.query_at` carregam branch, validade,
revision e hash. A consulta histórica escolhe a revisão observada até o instante
pedido e filtra a janela de validade.

Ainda existem superfícies legadas que recebem apenas `MemoryItem`, `status` ou
`memory_id`. Episódios, procedimentos, relações de catálogo e parte das APIs não
compartilham a mesma semântica bitemporal. Também falta uma política explícita
para cross-branch, ambientes e versões de produto.

### Critério de conclusão

Criar uma matriz de branch/escopo para todas as tools, contratos HTTP/MCP,
projeções e consultas. Uma busca cross-branch deve ser explícita e explicar de
qual branch veio cada evidência.

## L9 — A busca não garante verdade apenas por ter um bom score

O caminho canônico combina ledger, Qdrant e ranking híbrido; o grafo estrutural
é derivado dos heads ativos. O `memory_id` exibido na compatibilidade não muda
quando o título de uma revisão muda.

O score ainda mede relevância, não veracidade. A avaliação mais recente do alvo
ERPNext usou 100 PRs, 79 candidatos/interações, embeddings OpenRouter e
`qwen/qwen3-reranker-8b` com ZDR: MRR 0.9451, NDCG@10 0.9593, P@1 0.8987 e
Recall@10 1.0. Houve 78 reranks bem-sucedidos em 79 chamadas; a chamada
restante usou o fallback e ainda acertou o alvo em `hit@1`. Isso não prova que
extração estruturada, decisões arquiteturais, conflitos ou perguntas abertas
sejam verdadeiros ou confiáveis em produção.

Durante a validação do alvo, o Qdrant local não avaliou de forma consistente o
ramo `valid_to IS NULL` do filtro temporal. O adapter passou a fazer uma
segunda consulta estrutural e aplicar a janela de validade em Python quando a
primeira consulta não retorna pontos. Isso mantém a regressão local reproduzível,
mas ainda exige um contract test contra Qdrant servidor antes de considerar o
comportamento temporal equivalente em produção.

Faltam calibração por categoria, abstention com resposta “não sei”, reranking
grounded por evidência, avaliação multi-evidência e explicação de por que uma
revisão foi retornada.

## L10 — O investigador de erros ainda não é um code agent

O investigador atual agrupa incidentes, usa stack frames/arquivos/PRs como
contexto e pode chamar workers de LLM/OpenCode. Ainda não há um contrato comum de
capacidades para ler o repositório, editar arquivos, executar testes, produzir
diff, criar branch, fazer commit/push e abrir PR com prova.

Portanto, um diagnóstico textual não deve ser apresentado como correção aplicada.
O caminho desejado é:

```text
erro -> triagem -> contexto do ledger -> workspace descartável
     -> ferramentas do code agent -> patch proposto -> diff/policy review
     -> testes -> aprovação -> commit/PR -> feedback -> memória versionada
```

Ainda não foi escolhido um SDK. Antes disso, é necessário um spike comparando
sandbox, tool use, streaming, edição, testes, custo, permissões e múltiplos
provedores. O SDK deve ficar atrás de um `CodeAgentBackend` com capacidades
declaradas e limites de tempo/custo.

## L11 — Provedores e fallback não têm um contrato completo

Chat, embeddings, reranker e extração já são módulos distintos, e o benchmark
registra quando usa fallback. Ainda faltam registry de modelos, versão de
embedding por collection, migração dual, health checks uniformes e capacidades
de tool use/JSON schema declaradas.

O resultado deve sempre informar provider, modelo, dimensão, modo degradado e
origem da extração. Trocar o embedding exige reindexação controlada; não deve
ocorrer silenciosamente.

## L12 — Jobs e telemetria ainda são locais

Consolidação, materialização, scheduler, auditoria e telemetria ainda podem rodar
no processo. O outbox tem retry/dead-letter básico e claim/lease com token no
ledger, mas não há coordenação multi-instância validada, métricas duráveis,
alertas ou fencing completo no materializador Qdrant. Reiniciar a aplicação não
deve perder o histórico operacional nem duplicar uma aplicação.

O próximo passo é worker separado, fencing entre processos, correlation ID,
métricas de lag e persistência durável de auditoria, feedback e execução de
jobs.

## L13 — O investigador e o ledger ainda têm pouca validação E2E real

A suíte local cobre 445 testes aprovados e 1 ignorado, incluindo criação, update, histórico, CAS,
rollback, merge, invalidação, aliases, relações, migração, retry e lease do
materializador. `ruff`, `compileall` e `git diff --check` também passam.

O comando E2E foi executado, mas ficou bloqueado no bootstrap do Neo4j por
credenciais ausentes: `AuthError: Unsupported authentication token, missing key
credentials`. A porta TCP estava acessível, porém isso não prova autenticação
nem consistência do serviço.

Isso não substitui:

- contract tests com Neo4j e Qdrant servidores;
- queda/retentativa entre transação e outbox;
- migração real com backup e rollback;
- testes de concorrência em múltiplas instâncias;
- replay de bugs reais com workspace e patch;
- golden sets de obsolescência, conflito, relações e abstention.

O relatório reproduzido deve ser lido como **regressão local explícita**, não como
certificação de produção.

## L14 — Migração legada não inventa história

`LegacyMemoryMigrator` cria uma família, uma revisão `legacy_import`, evidência de
origem e alias por registro. IDs ambíguos são colocados em quarentena, o plano é
determinístico e há manifest/dry-run.

Se o `MemoryItem` antigo só guarda o estado atual, não existe informação para
reconstruir alterações anteriores. A migração deve dizer “histórico indisponível”
em vez de fabricar versões. Ainda faltam execução operacional com backup,
aprovação de cutover, comparação de contagens/checksums e reindexação paralela.

## Podemos usar o projeto agora?

Sim, desde que o escopo seja explícito:

- usar como memória assistida e busca sobre conhecimento com evidência;
- tratar resultados como hipóteses grounded, não como autoridade automática;
- operar mudanças semânticas via proposta e aprovação;
- usar o benchmark local para regressão de contratos;
- não habilitar auto-fix de código nem declarar Neo4j/Qdrant real validados sem
  executar os testes E2E correspondentes.

## Ordem de evolução até a fonte única de verdade

1. Validar o adapter Neo4j com serviços reais e fechar a migração legada.
2. Colocar autenticação/autorização forte na aprovação e auditoria.
3. Validar leases entre processos, reconciliação, backup e recuperação do outbox.
4. Definir políticas de obsolescência por categoria e dono de domínio.
5. Expandir relações, conflito, branch e temporalidade para todas as superfícies.
6. Criar contract/E2E/fault-injection tests e um gold set de conhecimento
   histórico.
7. Só então conectar um code-agent sandboxed com patch/testes/PR verificáveis.

Até esses critérios serem atendidos, a formulação correta é: **DecisionsSearch é um
sistema de memória versionada em consolidação, com uma implementação canônica
protegida e uma regressão local verificável — ainda não uma autoridade histórica
única em produção.**
