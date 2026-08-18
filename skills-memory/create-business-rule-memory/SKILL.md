---
name: create-business-rule-memory
description: "Captura uma BusinessRule durável em prosa estável, separada do PR e da implementação. Use quando o usuário disser 'cria a regra de negócio X', 'registra essa regra' ou quando a triagem detectar uma regra explícita no digest. Do NOT use para escolha técnica — create-architectural-decision-memory; padrão reutilizável evidenciado — create-code-pattern-memory; evolução — rule-blame."
version: 1.1.0
metadata:
  decisionssearch:
    memory_class: BusinessRule
    context_file: .decisionssearch/business.md
    related_skills: [decisionssearch-capture, create-pr-memory, rule-blame, link-pr-to-memory]
---

# Create Business Rule Memory

Você captura uma verdade de domínio que deve sobreviver ao PR: uma condição, obrigação, permissão, bloqueio ou resultado esperado do produto. A BusinessRule deve ser compreensível em prosa por alguém que não viu o código.

**CORE RULE:** Separe a regra da implementação. Escreva a regra e seu efeito em prosa estável, sem transformar nomes de classes, endpoints ou arquivos em conteúdo principal. Nunca persista sem preview e confirmação.

## When to activate

- Trigger phrases: "cria a regra de negócio", "registra essa regra", "isso é uma regra de negócio, guarda"
- Contexts: regra de produto/domínio explicitamente declarada; constraint de workflow, autorização ou propriedade de dados; regra nova/alterada identificada em PR ou digest

**Do NOT activate for:**

- escolha de tecnologia/estrutura com trade-offs → use create-architectural-decision-memory
- convenção de código reutilizável explicitamente evidenciada → use create-code-pattern-memory
- consultar a evolução de uma regra → use rule-blame
- registrar o PR ou sua narrativa operacional → use create-pr-memory

## Inputs

- rule_source (required): PR, diff, conversa ou item do digest de onde a regra vem. Fonte: sessão|digest|Git.
- mode (optional, default: standalone): standalone | orchestrated.

## Contrato de prosa

- summary deve ser uma frase ou pequeno parágrafo declarativo sobre a regra e seu efeito.
- details deve ser um parágrafo completo com escopo, condição, exceção, consequência e fronteira, quando conhecidos.
- Não usar uma lista de chamadas, nomes de métodos ou arquivos como substituto da regra.
- PR, arquivo, função e implementação pertencem à evidência/link; não devem aparecer como a única formulação da regra.
- Se a regra ainda for hipótese, ambígua ou depender de decisão técnica, não persistir como BusinessRule.

## Context load

- Carregar .decisionssearch/business.md; taxonomia oficial de domain/modules e macro-regras existentes.
- Se o arquivo não existir → sugerir decisionssearch-init e STOP.
- Verificar MCP DecisionsSearch com um memory.query trivial antes de qualquer escrita.

## Procedure

1. **Isolar a verdade de domínio** — extrair do PR/digest/conversa quem ou o que deve fazer o quê, em qual condição, com qual consequência. Escrever em prosa que continue válida se a implementação for trocada ou revertida.
   - Se restar uma escolha técnica com alternativas → encaminhar para create-architectural-decision-memory.
2. **Delimitar escopo e exceções** — registrar atores, estado, autorização, pré-condição, bloqueio e resultado. Perguntar o que não estiver evidenciado; nunca completar por suposição.
3. **Preencher campos estáveis** — usar title, summary e details em prosa; modules/domain somente da taxonomia. Referências ao PR, arquivos e métodos entram como evidência para links, não como definição da regra.
4. **Buscar duplicatas e conflitos** — memory.query com type=BusinessRule e termos da regra; buscar PRMemories por arquivo quando houver arquivo de implementação.
   - Se substitui uma regra antiga → criar a nova e usar memory.deprecate somente depois da confirmação da substituição.
   - Se detalha sem invalidar → memory.link com REFINES.
   - Se conflita sem prevalência definida → CONFLICTS_WITH e perguntar ao usuário.
5. **Self-Refine gate** — criticar contra:
   - summary/details são prosa de domínio, não uma descrição de código?
   - a regra sobrevive à troca/reversão do PR?
   - condição, consequência, escopo e exceções estão evidenciados?
   - modules/domain pertencem à taxonomia?
   - duplicata/conflito foi buscado?
   Refine até todas as respostas serem "sim"; só então mostrar o preview.
6. **Preview + confirmação** — mostrar o texto completo, evidências e relações propostas; persistir somente após "sim" explícito.
7. **Persistir e linkar** — memory.manual.create; PR que implementa pode ser ligado via memory.pr.link_memory com IMPLEMENTS, após verificação. Substituição usa memory.deprecate, não link manual.

## Output Schema

evidence é metadado de auditoria do preview. Não o enviar como campo extra para memory.manual.create se o schema da API não o suportar; manter a regra em summary/details e usar a fonte para o link/rationale.

~~~yaml
# project is optional; omit it to use the current workspace folder
category: "BusinessRule"
title: string
summary: string              # frase/parágrafo declarativo em prosa
details: string              # regra completa em prosa
modules: [string]
domain: [string]
event_date: ISO 8601
evidence:
  - source: string            # PR, work item, conversa ou arquivo
    fact: string              # o que a fonte sustenta
~~~

### Example

~~~yaml
# project omitted: DecisionsSearch derives it from the current workspace folder
category: "BusinessRule"
title: "Compatibilidade entre PileType e carga admissível"
summary: "Uma proposta só pode avançar quando o tipo de estaca escolhido suporta a carga admissível informada para a obra."
details: "Toda proposta deve usar um tipo de estaca cuja capacidade nominal seja maior ou igual à carga admissível calculada, incluindo a margem de segurança vigente. Quando a capacidade é insuficiente, a proposta não pode ser criada nem aprovada e o usuário deve receber uma explicação que permita corrigir a escolha."
modules: [propostas, estacas, cargas]
domain: [fundações, comercial]
event_date: "2026-06-28T14:30:00Z"
evidence:
  - source: "example-project#41"
    fact: "O PR bloqueia propostas incompatíveis e implementa a validação no fluxo de criação."
  - source: "services/proposal_service.py:88"
    fact: "A implementação aplica a condição de capacidade antes da criação."
~~~

## Verification

- [ ] memory.query por title retorna o nó criado
- [ ] details é uma regra em prosa e não depende de nomes de código
- [ ] Evidência mostra de onde a regra foi extraída
- [ ] Duplicatas, refinamentos e conflitos foram tratados explicitamente
- [ ] Output bate com o schema e nenhum anti-pattern foi disparado

## Anti-patterns

- Do NOT escrever "o service X chama Y" como se isso fosse a regra.
- Do NOT duplicar o summary do PR; isole a verdade de domínio em prosa.
- Do NOT registrar uma preferência técnica ou hipótese como BusinessRule.
- Do NOT persistir com modules/domain vazios ou fora da taxonomia.
- Do NOT criar cópia quando existe regra que deveria ser refinada ou substituída.

## Failure modes & recovery

- **MCP DecisionsSearch indisponível** → STOP, informe o usuário com instrução de setup. Nunca "persista depois".
- **Duplicata forte** → oferecer deprecate se substitui ou REFINES se detalha; nunca criar cópia silenciosa.
- **Regra e decisão misturadas** → separar os textos e encaminhar a decisão para create-architectural-decision-memory.
- **Escopo/condição não evidenciados** → perguntar; não preencher com convenção presumida.

## RECAP

- BusinessRule é verdade de domínio em prosa, independente da implementação.
- PR, arquivo e código são evidências e links, não substitutos da regra.
- Nunca persista sem preview, confirmação e tratamento de duplicata/conflito.
