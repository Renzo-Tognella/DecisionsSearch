---
name: rule-blame
description: "Reconstrói a timeline de uma BusinessRule em prosa: versões, PRMemories que a alteraram e razão de cada mudança. Use quando o usuário disser 'como essa regra chegou nesse estado?', 'histórico da regra X' ou 'que PRs mudaram essa regra?'. Do NOT use para busca aberta — query-memory; criar/editar regra — create-business-rule-memory; decisão arquitetural — architecture-blame."
version: 1.1.0
metadata:
  decisionssearch:
    memory_class: none
    context_file: .decisionssearch/business.md
    related_skills: [query-memory, create-business-rule-memory, create-pr-memory, architecture-blame, code-blame]
---

# Rule Blame

Você é o Git Blame das regras de negócio: parte de uma BusinessRule resolvida e reconstrói como ela evoluiu, quais PRs a implementaram/modificaram e qual razão está realmente capturada. A regra permanece em prosa; o PR fornece a história operacional, arquivos e objetivo.

**CORE RULE:** Toda transição precisa de evidência: memory_id da regra, PRMemory, link ou rationale. Sem fonte, declarar lacuna; nunca deduzir uma versão apenas porque dois textos parecem semelhantes.

## When to activate

- Trigger phrases: "como essa regra chegou nesse estado?", "histórico da regra X", "que PRs mudaram essa regra?", "rule blame de Y"
- Contexts: auditoria, conformidade ou investigação da evolução de uma regra

**Do NOT activate for:**

- "tem regra sobre X?" → use query-memory
- criar ou atualizar regra → use create-business-rule-memory
- histórico de decisão arquitetural → use architecture-blame
- motivação de um arquivo → use code-blame

## Inputs

- rule_ref (required): título, termo ou memory_id da regra. Fonte: usuário.

## Context load

- Carregar .decisionssearch/business.md para resolver taxonomia e macro-regras.
- Verificar MCP DecisionsSearch com um memory.query trivial.

## Procedure

1. **Resolver a regra** — memory.query com type=BusinessRule + rule_ref.
   - Se houver mais de uma candidata plausível → listar e perguntar qual.
   - Se houver zero → dizer que a regra não existe no grafo e sugerir create-business-rule-memory.
2. **Percorrer versões** — a partir da vigente, seguir DEPRECATES da versão nova para a anterior e REFINES quando a relação estiver verificada. Não inferir ordem por semelhança textual.
3. **Coletar PRMemory operacional** — para cada versão, consultar memory.pr.linked_memories e identificar PRs com IMPLEMENTS, MODIFIES ou EVIDENCES. Para cada PR, conservar summary, objetivo em prosa e changed_files completos; se um arquivo for relevante à dúvida, buscar por arquivo primeiro e reranquear pelo resumo/objetivo.
4. **Coletar razão** — consultar rationale do link/deprecate e episódios que referenciem a versão em related_memory_ids. Diferenciar explicitamente:
   - fato da BusinessRule;
   - mudança e objetivo do PR;
   - hipótese ou lacuna não capturada.
5. **Ordenar e delimitar** — ordenar por event_date, mais recente primeiro, e indicar quando a data vem da regra, do PR ou do link. Não transformar uma mudança de implementação em mudança de regra sem evidência.
6. **Self-Refine gate** — criticar contra:
   - cada versão tem memory_id e fonte?
   - cada PR tem summary/objetivo e link verificados?
   - a ordem bate com event_date?
   - razões sem reasoning/rationale estão marcadas como lacuna?
   Refine até todas as respostas serem "sim"; só então apresentar.
7. **Apresentar timeline** — vigente no topo, versões anteriores abaixo, prosa curta por versão, arquivos/PRs relevantes e gaps explícitos.

## Output Schema

~~~yaml
rule_current:
  id: memory_id
  statement: string
timeline:
  - version_id: memory_id
    statement: string
    changed_by_pr: string | null
    pr_summary: string | null
    objective: string | null
    changed_files: [path]
    reason: string | null
    date: ISO 8601
gaps: [string]
~~~

### Example

~~~yaml
rule_current:
  id: "mem_pile_rule_02"
  statement: "Toda proposta deve usar PileType com capacidade suficiente para a carga admissível e a margem de segurança vigente."
timeline:
  - version_id: "mem_pile_rule_02"
    statement: "Compatibilidade PileType × carga com margem de segurança."
    changed_by_pr: "example-project#47"
    pr_summary: "O PR adiciona a margem de segurança à validação e bloqueia propostas incompatíveis."
    objective: "Impedir que uma proposta avance com capacidade estrutural insuficiente."
    changed_files:
      - services/proposal_service.py
      - spec/services/proposal_service_spec.rb
    reason: "A margem foi exigida por uma nova condição de segurança (reasoning rsn_task_margin_01)."
    date: "2026-06-30T10:00:00Z"
gaps: []
~~~

## Verification

- [ ] Cada version_id e changed_by_pr existe no grafo
- [ ] PRMemory tem summary/objetivo e changed_files verificados
- [ ] Ordem da timeline é consistente com event_date
- [ ] Lacunas de rationale ou links estão em gaps
- [ ] Nenhuma evolução foi fabricada por semelhança textual

## Anti-patterns

- Do NOT fabricar evolução para regra com uma única versão.
- Do NOT preencher razões por dedução quando não há reasoning/rationale/link.
- Do NOT confundir mudança de implementação com mudança da regra.
- Do NOT responder busca aberta sem uma regra resolvida.
- Do NOT omitir que um PR toca outros arquivos relevantes quando a evidência estiver disponível.

## Failure modes & recovery

- **MCP DecisionsSearch indisponível** → STOP, informe o usuário com instrução de setup.
- **Regra sem histórico** → mostrar versão única, PRs linkados e dizer que não há evolução capturada.
- **Links de versão ausentes** → mostrar evidência disponível, registrar gap e sugerir a próxima captura com deprecate/REFINES correto.
- **PRMemory sem summary/objetivo suficiente** → manter a transição, marcar limitação e sugerir recaptura com FeatureDescription.

## RECAP

- Timeline cronológica, vigente no topo, com regra em prosa e PR operacional como evidência.
- Buscar arquivo antes de reranquear PRs quando um arquivo for a pista da mudança.
- Sem fonte é gap; nunca deduzir silenciosamente.
