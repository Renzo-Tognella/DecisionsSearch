---
name: create-code-pattern-memory
description: "Captura CodePattern somente quando existe evidência explícita de reutilização ou padronização, como múltiplas ocorrências ou uma instrução clara para repetir o idiom. Use quando o usuário disser 'registra esse padrão de código' ou quando a triagem encontrar esse tipo de evidência. Do NOT use para uma implementação isolada — mantenha-a em PRMemory; decisão — use create-architectural-decision-memory; regra — create-business-rule-memory."
version: 1.1.0
metadata:
  decisionssearch:
    memory_class: CodePattern
    context_file: .decisionssearch/code-patterns.md
    related_skills: [decisionssearch-capture, create-pr-memory, code-blame, decisionssearch-update]
---

# Create Code Pattern Memory

Você captura padrões de implementação que podem ser repetidos com segurança em outros lugares. Um CodePattern não é sinônimo de código bem escrito, convenção presumida ou ocorrência única: precisa de evidência explícita de que deve ser reutilizado.

**CORE RULE:** Compare com code-patterns.md e exija evidência explícita de reuso ou padronização antes de criar. Nunca persista sem preview e confirmação.

## When to activate

- Trigger phrases: "registra esse padrão de código", "documenta essa convenção", "isso virou padrão, captura"
- Contexts: PR ou revisão diz explicitamente que algo deve ser repetido; o mesmo idiom aparece em múltiplos arquivos/locais independentes; a triagem da decisionssearch-capture encontra uma convenção formalizada

**Do NOT activate for:**

- uma implementação one-off, mesmo que pareça elegante → mantenha em create-pr-memory/FeatureDescription
- escolha de tecnologia/design com trade-off → use create-architectural-decision-memory
- verdade de domínio/produto → use create-business-rule-memory
- "por que esse arquivo é assim?" → use code-blame

## Inputs

- pattern_source (required): PR, diff, código, revisão ou item do digest. Fonte: sessão|digest|Git.
- mode (optional, default: standalone): standalone | orchestrated.

## Evidência mínima obrigatória

Aceite somente se houver pelo menos uma das bases abaixo:

1. **Padronização explícita:** PR, review, guideline ou autor diz que a estrutura/idiom deve ser usado, repetido ou adotado como padrão.
2. **Repetição verificável:** o mesmo padrão aparece em pelo menos dois arquivos ou locais independentes, com referências concretas.
3. **Regra de replicação:** existe instrução operacional clara para aplicar o padrão em novas implementações, acompanhada de exemplos.

Similaridade visual, preferência do agente, um único arquivo, um único PR ou uma abstração local não bastam. Sem essa evidência, não crie CodePattern; capture o fato como PRMemory e, se necessário, encaminhe para BusinessRule ou ArchitecturalDecision.

## Context load

- Carregar .decisionssearch/code-patterns.md; a lista de padrões vigentes e anti-padrões é o baseline.
- Carregar .decisionssearch/business.md para modules/domain.
- Se os arquivos não existirem → sugerir decisionssearch-init e STOP.
- Verificar MCP DecisionsSearch com um memory.query trivial antes de qualquer escrita.

## Procedure

1. **Classificar a evidência** — registrar se a base é padronização explícita, repetição verificável ou ambas. Se só houver uma instância, STOP e manter em PRMemory.
2. **Diff contra o baseline** — comparar com padrões vigentes e anti-padrões do code-patterns.md.
   - Se já documentado → STOP com seção/referência.
   - Se diverge do documentado → destacar a divergência e perguntar se substitui; nunca sobrescrever silenciosamente.
3. **Isolar o padrão** — explicar em prosa o problema que resolve, quando aplicar, quando não aplicar e como reconhecer a estrutura em outro arquivo. Coletar exemplos concretos com file:line, trecho ou PR; repetição verificável exige pelo menos dois exemplos.
4. **Buscar duplicatas e links** — memory.query por CodePattern, regras que o padrão implementa e PRs que o introduziram. Não transformar o PR em padrão só porque há um link.
5. **Self-Refine gate** — criticar contra:
   - a evidência mínima está explícita e verificável?
   - o texto separa padrão reutilizável da instância do PR?
   - há exemplos suficientes e paths concretos?
   - modules/domain pertencem à taxonomia e não foram inventados?
   - duplicata foi buscada no documento e no grafo?
   Refine até todas as respostas serem "sim"; só então mostrar o preview.
6. **Preview + confirmação** — mostrar evidência, exemplos e payload completo; persistir somente com "sim" explícito.
7. **Persistir e atualizar** — memory.manual.create; links confirmados ficam para link-pr-to-memory. Marcar update_candidate: true para o próximo decisionssearch-update.

## Output Schema

evidence_basis, evidence e examples são metadados de auditoria do preview. Não os enviar como campos extras se a API de memória não os aceitar; incorporar a evidência factual em details/examples e enviar somente o payload suportado.

~~~yaml
# project is optional; omit it to use the current workspace folder
category: "CodePattern"
title: string
summary: string              # prosa: o padrão e a finalidade
details: string              # aplicação, limites e anti-uso, em prosa
evidence_basis: explicit_standard | repeated_instances | both
evidence: [string]           # fonte concreta da autorização/repetição
modules: [string]
domain: [string]
examples: [string]           # >=1; >=2 quando a base for repetição
event_date: ISO 8601
update_candidate: bool
~~~

### Example

~~~yaml
# project omitted: DecisionsSearch derives it from the current workspace folder
category: "CodePattern"
title: "Validações que cruzam entidades em services"
summary: "Validações que dependem de mais de uma entidade são centralizadas no service do agregado para que o fluxo, os erros e os testes compartilhem a mesma regra de aplicação."
details: "Use esse padrão quando a condição atravessar dois ou mais modelos. Models continuam responsáveis por invariantes próprias; o service coordena a validação e retorna erro de domínio tipado. Não use para validações puramente locais nem para uma única função que ainda não foi adotada como convenção."
evidence_basis: both
evidence:
  - "PR example-project#41 declara que validações de compatibilidade devem ficar em services."
  - "A mesma estrutura aparece em proposal_service.py:88 e contract_service.py:54."
modules: [propostas, contratos]
domain: [fundações, comercial]
examples:
  - "services/proposal_service.py:88 — validate_pile_compatibility()"
  - "services/contract_service.py:54 — validate_counterparty_limits()"
event_date: "2026-06-28T14:30:00Z"
update_candidate: true
~~~

## Verification

- [ ] A evidência explícita de reuso/padronização está citada
- [ ] Repetição tem exemplos em pelo menos dois locais independentes
- [ ] memory.query por title retorna o nó criado
- [ ] O padrão não duplica code-patterns.md nem uma memória existente
- [ ] Nenhum anti-pattern abaixo foi disparado

## Anti-patterns

- Do NOT criar CodePattern por uma única ocorrência ou por preferência do agente.
- Do NOT chamar estilo local, refactor isolado ou workaround temporário de padrão reutilizável.
- Do NOT aceitar \"parece repetível\" sem declaração, regra de replicação ou segunda ocorrência verificável.
- Do NOT pular o diff contra code-patterns.md.
- Do NOT persistir com modules vazio ou fora da taxonomia.

## Failure modes & recovery

- **MCP DecisionsSearch indisponível** → STOP, informe o usuário com instrução de setup. Nunca "persista depois".
- **code-patterns.md ausente** → sugerir decisionssearch-init e STOP; sem baseline não há diff confiável.
- **Evidência insuficiente** → manter a informação na PRMemory/FeatureDescription e não criar CodePattern.
- **Padrão diverge do documentado** → perguntar se substitui; se confirmado, criar a nova memória e deixar a depreciação para o fluxo explícito de substituição.
- **Modules/domain não mapeiam a taxonomia** → perguntar ou encaminhar para decisionssearch-update; não inventar valores.

## RECAP

- CodePattern exige evidência explícita de reuso ou padronização.
- Uma instância isolada fica em PRMemory, não vira padrão.
- Diff, preview, confirmação e links verificados continuam obrigatórios.
