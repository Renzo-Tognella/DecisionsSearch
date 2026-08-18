---
name: architecture-blame
description: "Reconstrói a timeline de uma ArchitecturalDecision em prosa: decisão vigente, alternativas descartadas, versões substituídas e PRMemories que implementaram cada uma. Use quando o usuário disser 'por que a arquitetura é assim?', 'por que usamos X?' ou 'qual a decisão vigente sobre Y?'. Do NOT use para busca aberta — query-memory; arquivo específico — code-blame; registrar decisão — create-architectural-decision-memory."
version: 1.1.0
metadata:
  decisionssearch:
    memory_class: none
    context_file: .decisionssearch/architecture.md
    related_skills: [query-memory, create-architectural-decision-memory, create-pr-memory, rule-blame, code-blame, decisionssearch-update]
---

# Architecture Blame

Você é o Git Blame da arquitetura: dado um tema, módulo ou tecnologia, reconstrói o que vigora, o que foi rejeitado, o que foi substituído e por quê. Cada decisão permanece em prosa; PRMemory fornece o objetivo, o resumo operacional e todos os arquivos que materializaram a escolha.

**CORE RULE:** Saída é timeline com evidência de AD, PR, alternativas e links. Sem fonte para uma substituição ou rationale, declarar lacuna; nunca completar a história por inferência.

## When to activate

- Trigger phrases: "por que a arquitetura é assim?", "por que usamos X?", "qual a decisão vigente sobre Y?", "architecture blame de Z"
- Contexts: investigação de escolha estrutural/tecnológica vigente e seu histórico

**Do NOT activate for:**

- "que decisões temos?" → use query-memory
- "por que esse arquivo/trecho é assim?" → use code-blame
- registrar decisão nova → use create-architectural-decision-memory

## Relação com architecture.md

A seção Decisões vigentes de .decisionssearch/architecture.md é a projeção rápida do topo das timelines. O grafo de ArchitecturalDecisions e os links verificados são a fonte da investigação; se documento e grafo divergirem, mostrar ambos e preferir o grafo como estado persistido.

## Inputs

- topic (required): módulo, componente, tecnologia ou tema. Fonte: usuário.

## Context load

- Carregar .decisionssearch/architecture.md para resolver o topic.
- Verificar MCP DecisionsSearch com um memory.query trivial.

## Procedure

1. **Resolver a AD** — memory.query com type=ArchitecturalDecision + topic, usando a tabela do architecture.md como filtro inicial.
   - Se houver mais de uma candidata plausível → listar e perguntar qual.
   - Se houver zero → dizer que não há decisão capturada e sugerir create-architectural-decision-memory.
2. **Percorrer substituições** — seguir DEPRECATES da decisão nova para a antiga até a raiz. Só chamar uma versão de substituída quando a aresta existir.
3. **Coletar prosa da decisão** — para cada versão, preservar summary, details e alternatives_considered sem reduzir a decisão a nomes de tecnologias.
4. **Coletar PRMemory operacional** — consultar memory.pr.linked_memories para IMPLEMENTS/MODIFIES/EVIDENCES. Para cada PR, incluir summary, objetivo e changed_files completos. Se o tema também apontar para arquivo, fazer busca exata por arquivo e reranquear os PRs pelo resumo/objetivo antes de expandir por tema.
5. **Coletar rationale e contexto** — consultar rationale de links/deprecate, reasoning via related_memory_ids e BusinessRules motivadoras. Separar fato, justificativa capturada e gap.
6. **Self-Refine gate** — criticar contra:
   - cada versão tem memory_id, prosa e alternativas?
   - cada PR/arquivo citado existe e está ligado?
   - ordem e direção de DEPRECATES estão corretas?
   - alguma substituição ou razão foi inferida sem link?
   Refine até todas as respostas serem "sim"; só então apresentar.
7. **Apresentar timeline** — decisão vigente no topo, alternativas e PRs associados; versões antigas abaixo com motivo da substituição e gaps explícitos.

## Output Schema

~~~yaml
decision_current:
  id: memory_id
  statement: string
  alternatives: [string]
timeline:
  - version_id: memory_id
    statement: string
    details: string
    alternatives: [string]
    implemented_by_pr: string | null
    pr_summary: string | null
    objective: string | null
    changed_files: [path]
    reason: string | null
    superseded_because: string | null
    date: ISO 8601
gaps: [string]
~~~

### Example

~~~yaml
decision_current:
  id: "adm_retrieval_file_first"
  statement: "A busca de PRMemory começa por arquivo e reranqueia os candidatos pelo summary e objetivo."
  alternatives:
    - "Busca semântica global — rejeitada por trazer PRs que falam do tema sem tocar o arquivo."
timeline:
  - version_id: "adm_retrieval_file_first"
    statement: "Busca exata por changed_files seguida de reranking semântico do resumo."
    details: "O filtro estrutural reduz falsos candidatos; a prosa do PR diferencia intenções distintas no mesmo arquivo."
    alternatives:
      - "Ordenação somente por recência — rejeitada porque não responde à intenção da pergunta."
    implemented_by_pr: "DecisionsSearch#12"
    pr_summary: "O PR reorganiza a recuperação de PRs para preservar o arquivo como primeiro estágio e usa o objetivo para a ordenação final."
    objective: "Explicar por que um arquivo mudou sem misturar PRs de outros módulos."
    changed_files:
      - skills-memory/code-blame/SKILL.md
      - skills-memory/query-memory/SKILL.md
    reason: "A busca semântica global produzia candidatos imprecisos para blame de arquivo."
    superseded_because: null
    date: "2026-08-12T12:00:00Z"
gaps: []
~~~

## Verification

- [ ] Cada version_id e implemented_by_pr da timeline existe no grafo
- [ ] alternatives_considered/alternatives foram preservadas em prosa
- [ ] PRs têm summary, objetivo e changed_files verificados
- [ ] Ordem da timeline e direção de DEPRECATES estão corretas
- [ ] Gaps estão listados, não silenciados

## Anti-patterns

- Do NOT fabricar histórico para decisão com uma versão.
- Do NOT omitir alternativas rejeitadas; elas explicam metade do valor da AD.
- Do NOT inferir substituição pela recência ou por similaridade de título.
- Do NOT responder busca aberta sem uma AD resolvida.
- Do NOT reduzir o PR a um arquivo quando a lista completa estiver disponível.

## Failure modes & recovery

- **MCP DecisionsSearch indisponível** → STOP, informe o usuário com instrução de setup.
- **Ramo reasoning inexistente** → mostrar AD + PRs + alternativas e declarar que o porquê do agente não foi capturado.
- **architecture.md desatualizado** → mostrar a divergência, usar o grafo como verdade e sugerir decisionssearch-update.
- **PRMemory sem summary/objetivo** → manter o vínculo, marcar gap e sugerir recaptura com FeatureDescription.

## RECAP

- Timeline com AD em prosa, alternativas e PR operacional como evidência.
- Arquivo, quando presente, é buscado primeiro; resumo/objetivo decide o reranking.
- Sem link ou fonte, é gap; a busca aberta é query-memory.
