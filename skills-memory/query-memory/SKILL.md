---
name: query-memory
description: "Busca memória por filtros estruturais e ranking semântico: quando houver arquivo, busca PRMemories por arquivo primeiro e reranqueia pelo resumo/objetivo em prosa; quando houver tema, busca regras, decisões, padrões, features e reasoning. Use quando o usuário disser 'já fizemos algo assim?', 'o que mudou no módulo X?' ou 'busca na memória por Y'. Do NOT use para timeline — use rule-blame/architecture-blame; porquê de arquivo — code-blame; criação — as create-*."
version: 1.1.0
metadata:
  decisionssearch:
    memory_class: none
    feature_description: "narrativa rica dentro de PRMemory"
    context_file: .decisionssearch/business.md
    related_skills: [rule-blame, architecture-blame, code-blame, create-pr-memory, decisionssearch-capture]
---

# Query Memory

Você é a interface de busca do grafo: recupera PRMemories operacionais, narrativas FeatureDescription, BusinessRules, ArchitecturalDecisions, CodePatterns e reasoning. A resposta é sustentada apenas pelos nós retornados e pelos links que foram realmente verificados.

**CORE RULE:** Se a pergunta nomeia um arquivo, a primeira etapa é busca exata em changed_files e a segunda é reranking pelo summary/objetivo em prosa do PR. Para qualquer pergunta, cite memory_ids e não invente memória, objetivo, regra ou relação.
## When to activate

- Trigger phrases: "já fizemos algo assim?", "o que mudou no módulo X?", "busca na memória", "tem regra sobre Y?", "o que mudou nesse arquivo?"
- Contexts: início de task nova; investigação por tema, projeto, módulo, domínio, arquivo, repo, PR ou work item

**Do NOT activate for:**

- "como essa regra chegou nesse estado?" → use rule-blame
- "por que a arquitetura/tecnologia X?" → use architecture-blame
- "por que esse arquivo é assim?" → use code-blame
- criar/capturar memórias → use decisionssearch-capture ou as create-*

## Inputs

- question (required): pergunta em linguagem natural. Fonte: usuário.
- filters (optional): projeto, classe, módulo/domínio, repo, pr_number, arquivo, work item. Fonte: pergunta + taxonomia.

## Context load

- Carregar .decisionssearch/business.md; a taxonomia traduz termos em módulos/domínios.
- Se o arquivo não existir → seguir sem filtro de taxonomia, avisando.
- Verificar MCP DecisionsSearch com um memory.query trivial.

## Contrato de busca

### Pergunta com arquivo

Use obrigatoriamente esta ordem:

1. normalizar o caminho para repo-relative;
2. executar memory.pr.query com changed_file_contains e filtros de projeto/repo quando disponíveis;
3. conservar todos os candidatos e todos os seus changed_files;
4. reranquear pela aderência da pergunta ao summary, objetivo e narrativa FeatureDescription, priorizando intenção e efeito operacional;
5. expandir para BusinessRule, ArchitecturalDecision ou CodePattern somente por links/evidência.

A busca semântica ampla por texto só é fallback, uma vez, depois de a busca exata retornar zero. A narrativa FeatureDescription não é um nó separado: ela é recuperada como parte da PRMemory e deve aparecer apenas quando ajudar a responder.

### Pergunta sem arquivo

Classifique a pergunta por classe e use o filtro mais estreito primeiro:

- PRMemory/FeatureDescription: mudanças, objetivo, efeito, PR, repo, work item;
- BusinessRule: verdade ou constraint de domínio;
- ArchitecturalDecision: escolha durável, trade-off e alternativas;
- CodePattern: padrão reutilizável explicitamente evidenciado;
- Reasoning: task, abordagem, tentativa, resultado e lições.

Para "já fizemos algo assim?", priorize memory.episode.query e reranqueie pelo objetivo/approach da task. Para identificador exato, faça lookup estrutural antes da busca textual.

## Procedure

1. **Classificar e extrair filtros** — identificar classe, projeto, repo, arquivo, PR, módulo/domínio e intenção. Não converter uma pergunta de blame em busca geral.
2. **Consultar na ordem correta** — arquivo: memory.pr.query por arquivo; identificador: filtro exato; tema: memory.query pela classe e taxonomia; task parecida: memory.episode.query.
3. **Reranquear** — em resultados de PR, comparar pergunta com summary, objetivo e FeatureDescription. Em regras/ADs/padrões, comparar com a prosa estável e a evidência, não com palavras isoladas. Registrar por que cada hit ficou no topo.
4. **Relaxar se vazio** — remover apenas o filtro mais restritivo e repetir UMA vez, informando que a busca foi ampliada. Se continuar vazio, dizer que não há memória e sugerir a skill de captura adequada.
5. **Expandir pelos links** — para os top hits, puxar PRs que implementam/modificam/evidenciam regras, ADs ou padrões. Não linkar episódios; eles usam related_memory_ids na criação.
6. **Self-Refine gate** — criticar contra:
   - cada afirmação tem memory_id ou link retornado?
   - a ordem arquivo → resumo/objetivo foi respeitada quando havia arquivo?
   - CodePattern aparece somente com evidência explícita de reuso?
   - a pergunta pedia timeline ou blame e deveria ser roteada?
   Refine até as respostas serem \"sim/não-aplicável\"; só então apresentar.
7. **Apresentar o mínimo útil** — resposta curta, hits ranqueados, classe, resumo em prosa, motivo da relevância e lacunas. Não despejar changed_files inteiros sem relação com a pergunta.
## Output Schema

~~~yaml
answer: string
search_strategy: string       # ex.: exact_file_then_summary_rerank ou typed_semantic_search
hits:
  - memory_id: string
    class: PRMemory | BusinessRule | ArchitecturalDecision | CodePattern | Reasoning
    summary: string
    why_relevant: string
    evidence: [string]
    changed_files: [path]      # preencher para PRMemory quando relevante
search_relaxed: bool
gaps: [string]
~~~

### Example

~~~yaml
answer: "Sim — o arquivo foi alterado por dois PRs. O mais relevante para a pergunta é o PR que moveu a validação para o service porque seu objetivo explícito era centralizar regras que cruzam entidades."
search_strategy: "exact_file_then_summary_rerank"
hits:
  - memory_id: "prm_example-project_41"
    class: PRMemory
    summary: "O PR move a validação de compatibilidade PileType × carga para o serviço de propostas e bloqueia propostas incompatíveis."
    why_relevant: "O summary e o objetivo explicam diretamente por que o arquivo concentra a lógica."
    evidence:
      - "changed_files contém services/proposal_service.py"
      - "PR #41 registra o objetivo de impedir propostas incompatíveis"
    changed_files:
      - services/proposal_service.py
      - spec/services/proposal_service_spec.rb
  - memory_id: "cp_domain_validation_services"
    class: CodePattern
    summary: "Validações que cruzam entidades vivem em services, não em models."
    why_relevant: "Está linkado ao PR e possui exemplos reutilizáveis em mais de um arquivo."
    evidence: ["link PR → CodePattern verificado"]
    changed_files: []
search_relaxed: false
gaps: []
~~~

## Verification

- [ ] Todo hit tem memory_id retornado pelo grafo
- [ ] Com arquivo, a primeira consulta foi exata e a ordem final veio do reranking por summary/objetivo
- [ ] answer só afirma o que os hits/evidências sustentam
- [ ] CodePattern tem evidência de reuso explícito
- [ ] Output bate com o schema e lacunas estão declaradas

## Anti-patterns

- Do NOT fazer busca semântica ampla antes de buscar o arquivo em changed_files.
- Do NOT inventar/parafrasear memórias que a query não retornou.
- Do NOT responder timeline de regra/decisão aqui; rotear para o blame correto.
- Do NOT promover uma ocorrência de PR a CodePattern sem evidência de reutilização.
- Do NOT relaxar filtros mais de uma vez sem avisar.

## Failure modes & recovery

- **MCP DecisionsSearch indisponível** → STOP, informe o usuário com instrução de setup.
- **Coleção vazia/projeto não inicializado** → sugerir decisionssearch-init ou decisionssearch-capture, conforme o caso.
- **Arquivo não encontrado em PRMemories** → executar o fallback uma vez, mostrar lacuna e sugerir create-pr-memory.
- **Summary/objetivo pobre** → não fingir precisão; reportar a limitação e sugerir recaptura com FeatureDescription rica.
- **Ramo reasoning inexistente** → responder com as demais classes e avisar que o reasoning ainda não foi capturado.

## RECAP

- Arquivo: busca exata primeiro, reranking por summary/objetivo depois.
- Tema: classe e filtro estreito primeiro; só nós e links verificados.
- FeatureDescription vive dentro da PRMemory; CodePattern exige evidência explícita de reuso.
