---
name: code-blame
description: "Explica por que um arquivo é assim usando busca exata por arquivo em PRMemories e reranking pelo resumo/objetivo em prosa, cruzados com Git Blame, reasoning e regras/decisões. Use quando o usuário disser 'por que esse arquivo é assim?', 'que PRs mexeram nesse arquivo?' ou 'qual a razão dessa mudança?'. Do NOT use para autoria de linha — use git blame direto; timeline de regra — rule-blame; decisão — architecture-blame."
version: 1.1.0
metadata:
  decisionssearch:
    memory_class: none
    context_file: .decisionssearch/code-patterns.md
    related_skills: [query-memory, create-pr-memory, rule-blame, architecture-blame, decisionssearch-capture]
---

# Code Blame

Você é o blame operacional do código: primeiro encontra os PRs que tocaram exatamente o arquivo; depois reranqueia esses candidatos pela aderência entre a pergunta e o summary/objetivo em prosa do PR. A resposta explica o porquê com evidência e separa o que Git mostra do que PRMemory capturou.

**CORE RULE:** Busca por arquivo vem antes de busca semântica. O reranking usa o resumo/objetivo do PR, não apenas similaridade de nomes ou scores do primeiro estágio. Granularidade de linha continua sendo responsabilidade do git blame direto.

## When to activate

- Trigger phrases: "por que esse arquivo é assim?", "que PRs mexeram nesse arquivo?", "qual a razão dessa mudança?", "code blame de X"
- Contexts: investigação da motivação de um arquivo ou conjunto de arquivos cuja história não é óbvia

**Do NOT activate for:**

- quem/quando mudou uma linha → use git blame direto
- evolução de regra de negócio → use rule-blame
- histórico de decisão arquitetural → use architecture-blame
- busca aberta na memória → use query-memory

## Inputs

- path (required): arquivo repo-relative; diretório pode ser expandido para seus arquivos. Trecho/linha é aceito, mas o resultado é consolidado por arquivo.
- question (optional): dúvida específica sobre a motivação; se ausente, usar "por que este arquivo mudou?".

## Context load

- Carregar .decisionssearch/code-patterns.md; um padrão seguido pelo arquivo entra somente como contexto, nunca como conclusão sem evidência.
- Verificar MCP DecisionsSearch com um memory.query trivial.

## Procedure

1. **Normalizar o path** — converter para repo-relative; se for diretório, enumerar os arquivos e informar que a resposta agregará os resultados.
2. **Buscar por arquivo primeiro** — para cada arquivo, usar memory.pr.query(project, repo, changed_file_contains=path); quando houver pr_number explícito, aplicar o filtro exato antes do texto livre. Conservar cada PR e sua lista completa de changed_files.
3. **Confirmar a cadeia no Git** — executar git log --follow --oneline -- <path> e, quando necessário, git blame -L <range> -- <path> para ligar linhas/commits a PRs. Commits sem PRMemory vão para uncaptured_prs, nunca para a cadeia capturada.
4. **Reranquear por resumo e objetivo** — ordenar os candidatos recuperados pelo arquivo segundo a aderência da pergunta ao summary, ao objetivo e à narrativa FeatureDescription do PR. Priorizar correspondência de intenção/efeito operacional; não promover um PR apenas porque o título ou o nome do arquivo contém a mesma palavra. Se a pergunta for ampla, usar recência apenas como desempate.
5. **Expandir evidências** — para os candidatos do topo, consultar memory.pr.linked_memories/memory.linked_prs e episódios que referenciem o PR ou a regra/decisão. Incluir BusinessRule, ArchitecturalDecision e CodePattern somente quando houver link e evidência concreta. Um padrão isolado permanece apenas como observação do PR.
6. **Fallback controlado** — se a busca exata por arquivo retornar zero, mostrar os resultados do Git como não-capturados e fazer uma única busca semântica pelo path + pergunta, claramente rotulada como fallback. Não substituir a busca por arquivo por uma busca ampla silenciosa.
7. **Self-Refine gate** — criticar contra:
   - a primeira etapa foi realmente changed_file_contains/Git, antes do reranking?
   - cada razão está sustentada pelo resumo/objetivo, diff, Git, reasoning ou link?
   - PRs sem memória estão separados?
   - a resposta não está respondendo autoria de linha nem inventando um padrão?
   Refine até todas as respostas serem "sim"; só então apresentar.
8. **Apresentar a cadeia** — do mais relevante ao menos relevante, com posição do reranking, resumo/objetivo, todos os arquivos quando úteis, razões sustentadas e lacunas explícitas.

## Output Schema

~~~yaml
file: path
question: string
search_strategy: "exact_file_then_summary_rerank"
matches:                         # mais relevante primeiro
  - pr: string                   # repo#numero
    memory_id: string
    rank_reason: string           # por que o resumo/objetivo venceu
    summary: string
    objective: string | null
    changed_files: [path]
    reason: string | null
    rules: [memory_id]
    decisions: [memory_id]
    patterns: [memory_id]
pattern_followed: string | null
uncaptured_prs: [string]
gaps: [string]
~~~

### Example

~~~yaml
file: "services/proposal_service.py"
question: "por que a validação de PileType foi colocada aqui?"
search_strategy: "exact_file_then_summary_rerank"
matches:
  - pr: "example-project#47"
    memory_id: "prm_example-project_47"
    rank_reason: "O resumo e o objetivo mencionam diretamente a margem de segurança e o bloqueio de propostas; o PR também altera o arquivo consultado."
    summary: "O PR adiciona margem de segurança à validação de compatibilidade entre PileType e carga admissível e bloqueia a criação quando a condição falha."
    objective: "Impedir que uma proposta avance com capacidade estrutural insuficiente."
    changed_files:
      - services/proposal_service.py
      - spec/services/proposal_service_spec.rb
    reason: "A regra de segurança passou a exigir margem sobre a capacidade nominal (reasoning rsn_task_margin_01)."
    rules: ["mem_pile_rule_02"]
    decisions: []
    patterns: []
pattern_followed: null
uncaptured_prs: ["example-project#33"]
gaps: []
~~~

## Verification

- [ ] A primeira consulta usou o arquivo em changed_files, não apenas texto semântico
- [ ] A ordem final foi reranqueada pelo summary/objetivo em prosa
- [ ] Cada PR e memória citados existem no grafo ou no Git indicado
- [ ] uncaptured_prs contém os PRs/commits do Git sem PRMemory
- [ ] Nenhuma conclusão de padrão, regra ou decisão foi feita sem evidência

## Anti-patterns

- Do NOT começar por busca semântica ampla quando há um arquivo identificável.
- Do NOT ordenar só pelo título, nome do arquivo, recência ou score bruto do primeiro estágio.
- Do NOT inventar razões quando o resumo, diff, reasoning ou link não as sustentam.
- Do NOT misturar PRs sem memória na cadeia capturada.
- Do NOT responder "quem mudou" ou prometer blame de linha nesta skill.

## Failure modes & recovery

- **MCP DecisionsSearch indisponível** → STOP, informe o usuário com instrução de setup.
- **Nenhum PRMemory toca o path** → mostrar git log/git blame como não-capturados e sugerir create-pr-memory/decisionssearch-capture.
- **Git checkout incompleto** → informar quais arquivos/históricos não puderam ser confirmados; não preencher a lacuna por inferência.
- **Resumo/objetivo insuficiente para reranking** → manter a ordem exata por arquivo, marcar gaps e sugerir recaptura do PR com FeatureDescription rica.
- **Ramo reasoning inexistente** → degradar para PR → regra/decisão, anotando que o porquê do agente não está capturado.

## RECAP

- Buscar por arquivo primeiro; reranquear pelo resumo e objetivo em prosa.
- PRs sem memória ficam separados e toda razão precisa de evidência.
- Git Blame direto responde autoria de linha; esta skill explica motivação operacional.
