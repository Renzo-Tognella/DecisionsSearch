---
name: create-architectural-decision-memory
description: "Captura uma ArchitecturalDecision durável em prosa, com contexto, constraints, trade-offs e alternativas rejeitadas. Use quando o usuário disser 'registra a decisão de usar X' ou quando a triagem encontrar uma escolha arquitetural explícita. Do NOT use para processo da task — capture-reasoning; regra de domínio — create-business-rule-memory; padrão reutilizável evidenciado — create-code-pattern-memory."
version: 1.1.0
metadata:
  decisionssearch:
    memory_class: ArchitecturalDecision
    context_file: .decisionssearch/architecture.md
    related_skills: [decisionssearch-capture, create-pr-memory, capture-reasoning, architecture-blame, decisionssearch-update]
---

# Create Architectural Decision Memory

Você documenta uma escolha estrutural ou tecnológica que deve orientar decisões futuras. A ArchitecturalDecision precisa explicar em prosa o que foi escolhido, por que foi escolhido, quais alternativas foram rejeitadas e qual impacto operacional é esperado.

**CORE RULE:** Sem pelo menos uma alternativa considerada e um rationale factual, não existe AD. Decisão, constraints e trade-offs devem estar em prosa; nunca persista sem preview e confirmação.

## When to activate

- Trigger phrases: "registra a decisão de usar X", "documenta essa escolha de arquitetura", "cria a AD de Y"
- Contexts: escolha de tecnologia, estrutura, integração ou estratégia resolvida com trade-off; decisão durável detectada no PR/digest

**Do NOT activate for:**

- plano, tentativa ou processo de uma task → use capture-reasoning
- "por que a arquitetura é assim?" → use architecture-blame
- regra de domínio → use create-business-rule-memory
- padrão de código repetível explicitamente evidenciado → use create-code-pattern-memory
- registrar a implementação operacional do PR → use create-pr-memory

## AD vs reasoning

- Decisão durável com alternativa e consequência futura → ArchitecturalDecision.
- Processo da task, tentativas, correções de rota e lições → capture-reasoning.
- Se o digest tiver ambos, criar a AD e fazer o episódio referenciar seu id em related_memory_ids; episódios não recebem link reverso.

## Contrato de prosa

- summary é um parágrafo declarativo com a escolha e o motivo principal.
- details é um parágrafo ou conjunto curto de parágrafos com constraints, trade-offs, impacto, escopo e condições de revisão.
- Cada item de alternatives_considered deve ser uma frase completa: alternativa + motivo concreto da rejeição.
- Código, arquivo e PR são evidências de implementação; não substituem o rationale da decisão.
- Não registrar uma preferência momentânea, uma tarefa em andamento ou um padrão local como AD.

## Inputs

- decision_source (required): PR, diff, discussão ou item do digest. Fonte: sessão|digest|Git.
- mode (optional, default: standalone): standalone | orchestrated.

## Context load

- Carregar .decisionssearch/architecture.md, especialmente "Decisões vigentes".
- Carregar .decisionssearch/business.md para modules/domain.
- Se os arquivos não existirem → sugerir decisionssearch-init e STOP.
- Verificar MCP DecisionsSearch com um memory.query trivial antes de qualquer escrita.

## Procedure

1. **Extrair a escolha** — registrar em prosa o problema, a escolha, constraints e impacto esperado. Separar o que foi decidido do que foi apenas tentado no PR.
   - Se for só processo de task → encaminhar para capture-reasoning.
2. **Coletar alternativas** — exigir pelo menos uma alternativa rejeitada e explicar o motivo factual: custo, risco, acoplamento, operação, segurança, desempenho ou compatibilidade. Se a fonte não trouxer a alternativa, perguntar ao usuário; não inventar.
3. **Buscar conflitos e relacionados** — memory.query por ArchitecturalDecision; consultar PRMemories por arquivos envolvidos e reranquear por summary/objetivo quando a decisão veio de um PR; buscar BusinessRules motivadoras.
   - Decisão conflitante → perguntar se a antiga deve ser deprecada ou se ambas CONFLICTS_WITH.
4. **Self-Refine gate** — criticar contra:
   - summary/details são prosa de decisão, não uma lista de implementação?
   - há alternativa rejeitada com motivo concreto?
   - constraints, trade-offs, impacto e escopo estão evidenciados?
   - modules/domain pertencem à taxonomia?
   - duplicata/conflito e PR implementador foram buscados?
   Refine até todas as respostas serem "sim"; só então mostrar o preview.
5. **Preview + confirmação** — mostrar o texto completo, alternativas, evidências e relações propostas; persistir somente após "sim" explícito.
6. **Persistir e verificar** — memory.manual.create com category ArchitecturalDecision; PR confirmado usa memory.pr.link_memory com IMPLEMENTS. Substituição confirmada usa memory.deprecate, que cria DEPRECATES automaticamente. Marcar update_candidate: true para decisionssearch-update.

## Output Schema

evidence é metadado de auditoria do preview. Não o enviar como campo extra para memory.manual.create se o schema da API não o suportar; manter decisão, constraints e trade-offs em summary/details/alternatives_considered.

~~~yaml
# project is optional; omit it to use the current workspace folder
category: "ArchitecturalDecision"
title: string
summary: string                    # escolha + motivo, em prosa
details: string                    # constraints, trade-offs e impacto, em prosa
modules: [string]
domain: [string]
alternatives_considered: [string]  # frases completas, >=1
event_date: ISO 8601
update_candidate: bool
evidence:
  - source: string
    fact: string
~~~

### Example

~~~yaml
# project omitted: DecisionsSearch derives it from the current workspace folder
category: "ArchitecturalDecision"
title: "Busca por arquivo seguida de reranking pelo resumo do PR"
summary: "A recuperação de PRMemories deve começar por correspondência exata em changed_files e só depois ordenar os candidatos pela aderência do summary e do objetivo à pergunta."
details: "A decisão separa precisão estrutural de relevância semântica. O arquivo reduz o espaço de candidatos e evita que PRs de outros módulos entrem na cadeia; o resumo e o objetivo distinguem mudanças diferentes no mesmo arquivo. A estratégia deve ser revisada se PRMemory ganhar indexação semântica própria ou se a cobertura de arquivos ficar incompleta."
modules: [busca, pr-memory, code-blame]
domain: [retrieval, engenharia de software]
alternatives_considered:
  - "Busca semântica global foi rejeitada porque pode recuperar PRs que falam do tema, mas não alteram o arquivo investigado."
  - "Ordenação somente por recência foi rejeitada porque não explica qual PR melhor responde à intenção da pergunta."
event_date: "2026-08-12T12:00:00Z"
update_candidate: true
evidence:
  - source: "contrato de avaliação das skills"
    fact: "A busca por arquivo deve preceder o reranking por resumo/objetivo."
~~~

## Verification

- [ ] memory.query por title retorna o nó criado
- [ ] alternatives_considered contém pelo menos uma alternativa com motivo factual
- [ ] summary/details estão em prosa e não são apenas nomes de arquivos ou funções
- [ ] AD conflitante foi deprecada ou marcada CONFLICTS_WITH somente após confirmação
- [ ] Em modo orquestrado, link IMPLEMENTS do PR está presente após o passo de links

## Anti-patterns

- Do NOT registrar decisão sem alternativa rejeitada e rationale.
- Do NOT escrever detalhes de implementação no lugar da decisão e do trade-off.
- Do NOT capturar plano de task como AD.
- Do NOT ignorar uma decisão vigente conflitante.
- Do NOT transformar uma ocorrência de código em CodePattern ou AD sem evidência da escolha.

## Failure modes & recovery

- **MCP DecisionsSearch indisponível** → STOP, informe o usuário com instrução de setup. Nunca "persista depois".
- **Nenhuma alternativa recuperável** → não persistir; perguntar ao usuário ou capturar apenas o processo via capture-reasoning.
- **Decisão substituída sem replaced_by confirmado** → não chamar deprecate; manter a AD antiga ativa e pedir confirmação.
- **Rationale insuficiente** → marcar a lacuna e recapturar o PR/digest; não completar com preferência do agente.

## RECAP

- ArchitecturalDecision é escolha durável, alternativa rejeitada e rationale em prosa.
- Processo da task é reasoning; regra é BusinessRule; padrão reutilizável requer evidência própria.
- Nunca persista ou deprecie sem preview e confirmação explícita.
