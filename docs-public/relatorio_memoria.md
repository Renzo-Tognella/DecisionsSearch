# Relatório técnico — como funciona a memória do DecisionsSearch

> Documento público sobre o comportamento implementado. Ele explica o fluxo de
> memória, suas garantias e seus limites; não transforma uma intenção futura em
> capacidade já validada.

## Resumo executivo

O DecisionsSearch é uma camada de memória de engenharia para agentes de IA. Ele
recebe contexto de tarefas, commits, pull requests, documentos e conversas,
mas não transforma automaticamente todo texto em conhecimento. O material passa
por sanitização, extração estruturada, gates de admissão, proposta e aprovação
antes de chegar ao ledger canônico.

Cada memória pertence a um projeto. Quando o agente não informa `project`, o
sistema obtém o nome da raiz Git — ou da pasta atual em um workspace sem Git — e
usa esse valor tanto na gravação quanto na busca. A busca aplica essa partição
antes de consultar Qdrant, Neo4j ou o ledger; depois combina sinais densos,
sparse e estruturais por RRF.

```text
pasta do agente
    ↓
resolução do projeto
    ↓
evento bruto → sanitização → extração de candidato
    ↓
admissão → proposta → aprovação/CAS
    ↓
revisão + head no ledger canônico → outbox
    ↓
projeção derivada no Qdrant
    ↓
filtro por projeto → busca híbrida → resposta com evidências
```

## 1. O que é uma memória

Uma memória é conhecimento durável, tipado e rastreável que pode ajudar outra
task depois que a sessão atual terminar. Ela tem, conforme a categoria,
atributos como:

- projeto, categoria, domínio e módulos;
- título, resumo e detalhes para recuperação e leitura humana;
- objetivo, gatilho, stakeholders, arquivos relacionados e exemplos;
- peso, confiança, validade temporal e estado do ciclo de vida;
- evidências que apontam para commit, diff, PR, conversa ou documento;
- relações com outras memórias e identidade estável.

Uma transcrição, um diff, uma mensagem ou um embedding são sinais de entrada.
Eles não são, sozinhos, uma memória canônica. A resposta `no_memory` é válida e
preferível a criar uma afirmação sem sustentação.

## 2. Como o projeto é resolvido

`project_context.resolve_project()` resolve a partição no momento da operação.
A ordem de precedência é:

1. `DECISIONSSEARCH_PROJECT`, quando existe;
2. o argumento `project` explícito;
3. o nome da raiz do repositório Git;
4. o nome da pasta atual, se não houver uma raiz Git.

O argumento explícito existe para importações, backfills e jobs que processam
mais de um projeto. Para o uso normal de um agente, o recomendado é omitir o
argumento e deixar o workspace definir a partição.

### Exemplo

Se o agente trabalha em:

```text
/workspaces/billing-service/src/application
```

e `/workspaces/billing-service` é a raiz Git, uma chamada sem `project` recebe:

```text
project = "billing-service"
```

Esse valor é associado ao candidato e preservado na proposta, na revisão, no
payload do Qdrant e no registro consultado no grafo. Uma consulta iniciada no
mesmo workspace recupera somente a partição `billing-service`.

Essa separação é lógica. Ela evita mistura acidental de contexto, mas não
substitui autenticação, autorização, isolamento de infraestrutura ou uma
política de acesso entre equipes.

## 3. Caminho de escrita

### 3.1 Entrada e landing zone

As interfaces MCP, HTTP, hooks de commit, jobs e integrações fornecem entradas
estruturadas ou brutas. `memory.ingest_raw` preserva o evento sanitizado na
landing zone JSONL para rastreabilidade. A landing zone é um registro de entrada,
não o armazenamento de memória final.

### 3.2 Sanitização e contexto

O payload é validado e sanitizado antes de ser enviado ao extrator. O resolvedor
de contexto determina projeto, domínio e categoria provável. A categoria
provável é uma pista; ela não substitui a validação de admissão.

### 3.3 Extração estruturada

O extrator produz um ou mais `MemoryCandidate`s. Um candidato contém os campos
que permitem explicar o conhecimento e recuperá-lo depois, incluindo título,
resumo, detalhes, categoria, contexto, peso e evidências.

Um único evento pode produzir zero, um ou mais candidatos quando houver
conhecimento independente. Uma mudança trivial ou uma ocorrência isolada não
deve ser promovida apenas porque passou por um LLM.

### 3.4 Gates de admissão

Os gates são encadeados nesta ordem:

1. **Projeto:** o candidato precisa ter uma partição não vazia;
2. **Evidência:** precisa apontar para uma fonte concreta;
3. **Duplicidade/refinamento:** procura memória semelhante no mesmo projeto e
   categoria, decidindo entre criar, atualizar ou refinar;
4. **Contexto:** verifica campos exigidos pela categoria;
5. **Peso:** rejeita conhecimento abaixo do limiar, salvo exceções governadas.

Os gates não são um classificador de verdade absoluta. Eles são uma barreira
para reduzir memória sem contexto, duplicada ou sem proveniência.

## 4. Proposta, aprovação e ledger

Com o ledger canônico habilitado, a escrita do agente termina em uma
`ChangeProposal`. A proposta contém:

- estado anterior e estado proposto;
- diff por campo;
- evidências e motivo;
- heads esperados para compare-and-swap;
- `preview_hash` para impedir a aplicação de um preview alterado.

O operador ou uma política confiável aprova a proposta. O agente não aprova a
própria escrita. O apply verifica a decisão, o hash e os heads; se outro escritor
publicou antes, o CAS falha e a proposta precisa ser revisada.

Quando aplicada, a operação cria atomicamente no ledger persistente:

| Entidade | Função |
|---|---|
| `MemoryFamily` | identidade lógica estável da memória |
| `MemoryRevision` | snapshot imutável do conteúdo e da evidência |
| `MemoryHead` | versão publicada para escopo e branch |
| `MemoryAlias` | compatibilidade com IDs legados |
| `RevisionTransition` | update, supersessão, invalidação, rollback ou merge |
| `RelationAssertion` | relação tipada e auditável entre memórias |
| `OutboxEvent` | sinal idempotente para atualizar projeções |

Alterar título, resumo ou contexto cria uma revisão nova. A revisão anterior
continua disponível para histórico, validade temporal, blame e auditoria.

## 5. Armazenamento

### Neo4j e ledger

No caminho de produção, `Neo4jMemoryLedger` é a fonte canônica para famílias,
revisões, heads, aliases, evidências, propostas, aprovações, relações e outbox.
O grafo também oferece contexto estrutural, como relações entre memórias,
projetos, categorias, domínios e arquivos.

### Qdrant

Qdrant é uma projeção derivada para recuperação. O payload materializado inclui
projeto, família, revisão, categoria, branch, estado e validade.

- o vetor denso recupera significado semântico;
- o vetor sparse, quando habilitado, recupera termos técnicos e coincidências
  lexicais;
- o filtro `project` é aplicado no backend antes dos candidatos serem retornados;
- materialização e reprocessamento são idempotentes via outbox.

Se a projeção estiver atrasada ou inconsistente, ela deve ser reconciliada a
partir do ledger; Qdrant não pode ser usado para inventar uma revisão canônica.

### JSONL

JSONL é usado para landing zone, auditoria local e snapshots de regressão. Ele
não substitui o ledger persistente nem significa que o modo HTTP/MCP esteja
operando sem Neo4j e Qdrant.

## 6. Caminho de leitura

Uma chamada `memory.query` ou uma consulta equivalente segue este fluxo:

1. resolve o projeto do workspace ou do override;
2. seleciona heads/revisões válidos por projeto, categoria, branch e janela;
3. consulta Qdrant denso e, se habilitado, Qdrant sparse com o mesmo filtro;
4. consulta o ledger/grafo pela mesma partição;
5. descarta, na fronteira de fusão, qualquer candidato cujo `project` não seja
   exatamente o projeto resolvido;
6. combina as listas por Reciprocal Rank Fusion (RRF);
7. aplica, quando configurados, ativação espalhada, score composto e reranking;
8. devolve os candidatos com identidade, contexto, score, origem e evidências.

O score denso, sparse, RRF ou reranker mede relevância para a pergunta. Ele não
é uma prova de que a memória está correta. O agente deve verificar evidências e
se abster quando o contexto recuperado não for suficiente.

## 7. Categorias e formas de uso

As seis primeiras linhas da tabela são categorias semânticas de
`MemoryCandidate`/`MemoryItem`. Memória episódica e procedural são superfícies
de memória separadas, com serviços e consultas próprios; não são valores da
mesma enumeração de categorias semânticas. Elas podem se relacionar a memórias
semânticas por IDs relacionados e continuam submetidas à partição do projeto.

| Categoria | O que representa |
|---|---|
| `BusinessRule` | restrição ou comportamento obrigatório do domínio |
| `ArchitecturalDecision` | escolha, motivação, trade-offs e alternativas rejeitadas |
| `DesignRule` | convenção durável de código, estrutura ou interação |
| `DesignPattern` | solução recorrente de design ou interação |
| `CodePattern` | padrão reutilizável de implementação com exemplos |
| `FeatureDescription` | gatilho, objetivo, atores e fluxo de uma feature |
| `PRMemory` | o que um pull request mudou e por quê |
| Memória episódica | o que aconteceu em uma task específica e seu resultado |
| Memória procedural | sequência repetível de passos para executar uma task |

As relações também têm significado distinto:

- PR → memória: `IMPLEMENTS`, `EVIDENCES`, `MODIFIES`;
- memória → memória: `RELATED_TO`, `DEPENDS_ON`, `REFINES`, `DEPRECATES`,
  `CONFLICTS_WITH`, `EVOLVES_FROM`.

Para substituir uma regra ou decisão, use a operação governada de depreciação.
Não crie um link genérico e apague a memória anterior: a supersessão deve
preservar lineage e motivo.

## 8. Exemplos de chamadas

### Capturar texto bruto no projeto atual

```text
memory.ingest_raw(
  source_kind="document",
  payload="As validações de entrada usam guard clauses."
)
```

O `project` é derivado da pasta de trabalho, o texto é sanitizado, candidatos
são extraídos e somente os que passarem por admissão seguem para proposta.

### Consultar conhecimento do projeto atual

```text
memory.query(
  query_text="Como validamos entradas neste serviço?",
  top_k=5
)
```

O agente não precisa repetir o nome do projeto. A busca usa a pasta atual, filtra
essa partição antes do retrieval e retorna o contexto recuperável.

### Importar uma partição explícita

Jobs de backfill ou processamento multi-projeto podem informar `project` ou
configurar `DECISIONSSEARCH_PROJECT`. Esse é um override operacional e deve ser
registrado junto ao job para que a origem da partição fique clara.

## 9. Limites e leitura correta dos resultados

O sistema possui testes locais para resolução de projeto, ingestão, filtros
Qdrant/Neo4j, propagação nos ramos híbridos e exclusão antes do RRF. Os testes
de isolamento estão em
[`tests/unit/test_project_scoping_ingestion.py`](../tests/unit/test_project_scoping_ingestion.py),
[`tests/unit/test_project_scoping_search.py`](../tests/unit/test_project_scoping_search.py)
e [`tests/unit/test_project_scoping_tools.py`](../tests/unit/test_project_scoping_tools.py).
Execute-os com:

```bash
uv run pytest tests/unit/test_project_scoping_*.py -q
```

Isso valida o contrato de aplicação, não substitui um contrato E2E contra
serviços reais.

Ainda exigem validação operacional:

- Neo4j e Qdrant reais com autenticação, falha e reconciliação;
- autenticação/autorização corporativa para aprovação;
- políticas de obsolescência e conflito por domínio;
- calibração de abstention e grounding por evidência;
- concorrência multi-instância, backup, restore e migração legada.

Portanto, a memória deve ser usada como contexto assistido e verificável. Ela
preserva proveniência e histórico para ajudar decisões; não substitui revisão
humana, documentação normativa ou controles de segurança.

## Referências

- [`README.md`](../README.md) e [`README.pt-BR.md`](../README.pt-BR.md): uso e
  configuração;
- [`instalacao.md`](instalacao.md): instalação e operação suportadas;
- [`ARCHITECTURE.md`](../ARCHITECTURE.md): arquitetura e contratos técnicos;
- [`LIMITATIONS.md`](../LIMITATIONS.md): limites e evidências atuais;
- [`relatorio_resultados.md`](relatorio_resultados.md): resultados e limites
  reproduzíveis;
- [`relatorio_resultados.pdf`](relatorio_resultados.pdf): versão visual pública.
