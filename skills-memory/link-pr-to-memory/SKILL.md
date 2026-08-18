---
name: link-pr-to-memory
description: "Cria links tipados entre PRMemory e BusinessRule, ArchitecturalDecision ou CodePattern quando o PR e a evidência sustentam a relação. Use quando o usuário disser 'linka o PR X à regra Y', 'conecta essas memórias' ou como passo final da decisionssearch-capture. Do NOT use para criar memórias, linkar episódios ou inventar um nó FeatureDescription separado."
version: 1.1.0
metadata:
  decisionssearch:
    memory_class: none
    feature_description: "já está contida na narrativa do PRMemory"
    context_file: none
    related_skills: [decisionssearch-capture, create-pr-memory, create-business-rule-memory, create-architectural-decision-memory, create-code-pattern-memory, query-memory]
---

# Link PR to Memory

Você transforma PRMemory, BusinessRule, ArchitecturalDecision e CodePattern em contexto navegável por arestas tipadas. O PRMemory já contém a FeatureDescription rica; ela não é criada como nó separado nem recebe link artificial.

**CORE RULE:** Use a relação mais específica sustentada por evidência concreta. Nunca linke sem verificar os nós, sem rationale factual e sem preview/confirmação explícita.

## When to activate

- Trigger phrases: "linka o PR X à regra Y", "conecta essas memórias", "cria o link entre PR e decisão"
- Contexts: passo final da decisionssearch-capture, depois que os nós existem; pós-criação de uma memória que tem PR implementador

**Do NOT activate for:**

- criar memórias → use create-*
- consultar o que já está linkado → use query-memory ou os blames
- conectar episódio de reasoning → related_memory_ids na criação do episódio
- criar ou linkar uma FeatureDescription separada → ela faz parte do PRMemory

## Inputs

- source (required): memory_id de origem, normalmente PRMemory. Fonte: sessão|digest.
- targets (required): lista de memory_id, relação proposta e rationale. Fonte: create-* ou usuário.
- mode (optional, default: standalone): standalone | orchestrated.

## Relações válidas

### PRMemory → MemoryItem

Usar memory.pr.link_memory:

| Relação | Use quando |
|---|---|
| IMPLEMENTS | o diff implementa explicitamente uma BusinessRule ou ArchitecturalDecision |
| EVIDENCES | o PR fornece evidência de uma regra/AD/CodePattern, mas não é a implementação direta |
| MODIFIES | o PR altera o conteúdo ou comportamento representado pela memória existente |

Um CodePattern só pode ser alvo quando a memória já passou pelo gate de evidência explícita de reutilização/padronização. Um único uso no PR não basta.

### MemoryItem → MemoryItem

Usar memory.link:

| Relação | Use quando |
|---|---|
| REFINES | a nova memória especifica/detalha outra sem invalidá-la |
| CONFLICTS_WITH | duas memórias são incompatíveis e a prevalência ainda não foi resolvida |
| DEPENDS_ON | uma memória só faz sentido dado o contexto da outra |
| EVOLVES_FROM | há evolução conceitual sem substituição/depreciação |
| RELATED_TO | associação real, quando nenhuma relação mais específica é verdadeira |

Substituição explícita de BusinessRule/ArchitecturalDecision é memory.deprecate(memory_id, replaced_by, rationale), não memory.link manual.

## Procedure

1. **Verificar existência e tipo** — memory.get/memory.query do source e de cada target. Confirmar que o source é PRMemory para a API PR→MemoryItem e que nenhum alvo é episode_id. FeatureDescription não é alvo separado.
   - Se target inexistente → oferecer a skill create-* correta e STOP o link.
   - Em modo orchestrated → executar somente depois de todas as criações terminarem.
2. **Verificar evidência** — para um PR, consultar o summary, objetivo em prosa, FeatureDescription, changed_files completos, diff/PR e work item. Para um CodePattern, confirmar a evidência explícita de reuso/padronização; para regra/AD, confirmar que o texto da memória é sustentado.
3. **Escolher a API e a relação** — source PRMemory usa memory.pr.link_memory; source MemoryItem usa memory.link. Não trocar IMPLEMENTS por RELATED_TO por conveniência.
4. **Escrever rationale** — uma frase factual com arquivo/PR/objetivo/efeito. Bom: "PR #41 introduz a validação no serviço e bloqueia propostas incompatíveis, implementando a BusinessRule X." Ruim: "Parece relacionado."
5. **Self-Refine gate** — criticar contra:
   - API correta e relação mais específica?
   - source/targets existem e não são episódios?
   - rationale cita evidência concreta do PR ou da memória?
   - nenhum link é duplicado ou substitui depreciação?
   - FeatureDescription foi tratada como parte do PRMemory, sem nó fantasma?
   Refine até todas as respostas serem "sim"; só então mostrar o preview.
6. **Preview + confirmação** — mostrar source, target, relação e rationale completos; criar somente com "sim" explícito.
7. **Criar e verificar** — executar a API apropriada e reconsultar as arestas. Informar links criados, verificados e falhos separadamente.

## Output Schema

~~~yaml
links_created:
  - source: memory_id
    target: memory_id
    relation: IMPLEMENTS | EVIDENCES | MODIFIES | REFINES | CONFLICTS_WITH | DEPENDS_ON | EVOLVES_FROM | RELATED_TO
    rationale: string
links_verified: int
feature_description_links: 0       # sempre zero: a narrativa vive no PRMemory
~~~

### Example

~~~yaml
links_created:
  - source: "prm_example-project_41"
    target: "mem_pile_rule_01"
    relation: IMPLEMENTS
    rationale: "PR #41 altera services/proposal_service.py e bloqueia propostas com PileType incompatível, implementando a regra de compatibilidade."
  - source: "prm_example-project_41"
    target: "cp_domain_validation_services"
    relation: EVIDENCES
    rationale: "O PR aplica a estrutura em dois services e a memória CodePattern contém evidência explícita de reutilização da convenção."
links_verified: 2
feature_description_links: 0
~~~

## Verification

- [ ] Para cada link criado, memory.get/consulta da origem lista a aresta correta
- [ ] links_verified == len(links_created)
- [ ] Nenhum target é episódio ou FeatureDescription inexistente
- [ ] CodePattern alvo tem evidência explícita de reuso
- [ ] Nenhum rationale depende só de semelhança de nomes

## Anti-patterns

- Do NOT usar RELATED_TO quando relação mais forte é verdadeira.
- Do NOT linkar por nome parecido sem diff, summary, objetivo, work item ou texto da memória.
- Do NOT linkar para nó inexistente, episódio ou FeatureDescription fantasma.
- Do NOT usar link manual para substituição que exige deprecate.
- Do NOT declarar sucesso sem reconsultar as arestas.

## Failure modes & recovery

- **MCP DecisionsSearch indisponível** → STOP, informe o usuário com instrução de setup. Nunca "persista depois".
- **Target inexistente** → oferecer create-* correta; nunca linkar para id fantasma.
- **Target é episódio/FeatureDescription** → recusar; explicar related_memory_ids para episódio e PRMemory para FeatureDescription.
- **Relação de CodePattern sem evidência** → não criar link; manter o padrão como não comprovado.
- **Falha no meio da lista** → informar quais links foram criados/verificados e retomar sem recriar os confirmados.

## RECAP

- PRMemory contém a FeatureDescription; não há link separado para ela.
- Duas APIs, relação mais específica e rationale factual são obrigatórios.
- Criou → verificou; preview e confirmação continuam obrigatórios.
