---
name: decisionssearch-init
description: "Configura o DecisionsSearch num projeto consumidor: cria .decisionssearch/ (business.md, architecture.md, code-patterns.md, state.json) via Q&A guiado, instala as skills de memória e registra o projeto no grafo. Use quando o usuário disser 'decisionssearch init', 'configurar o decisionssearch', 'instalar as skills de memória' num projeto que ainda não tem .decisionssearch/. Do NOT use for atualizar um .decisionssearch/ existente — use `decisionssearch-update`; nem para capturar memórias — use `decisionssearch-capture`."
version: 1.0.0
metadata:
  decisionssearch:
    memory_class: none
    context_file: none
    related_skills: [decisionssearch-update, decisionssearch-capture]
---

# DecisionsSearch Init

Você é o onboarding do DecisionsSearch: transforma um repositório cru num projeto com memória organizacional — contexto de negócio explícito, skills instaladas e nó de projeto no grafo.

**CORE RULE:** Detecte antes de perguntar — nunca pergunte o que dá pra inferir do repo. Nunca grave `.decisionssearch/` sem preview e confirmação.

## When to activate

- Trigger phrases: "decisionssearch init", "configura o decisionssearch", "instala as skills de memória", "setup do decisionssearch"
- Contexts: projeto sem diretório `.decisionssearch/`

**Do NOT activate for:**
- `.decisionssearch/` já existe e precisa refletir memórias novas → use `decisionssearch-update`
- capturar memórias de um PR/sessão → use `decisionssearch-capture`
- perguntas sobre o que é o DecisionsSearch → apenas responda conversacionalmente

## Inputs

- `project_root` (optional, default: cwd): raiz do projeto consumidor. Fonte: sessão.
- Respostas do Q&A de negócio. Fonte: usuário (funil do Procedure, passo 3).

## Context load

- Nenhum `.decisionssearch/` a carregar (esta skill o cria).
- Verificar MCP DecisionsSearch com um `memory.query` trivial antes de qualquer escrita.

## Procedure

1. **Detectar contexto** — ler `README.md`, `CLAUDE.md`, `AGENTS.md`, `git remote -v`, estrutura de pastas (2 níveis), linguagem dominante (extensões predominantes).
   - Reason: pré-preencher o máximo do Q&A; setor/produto/stack muitas vezes já estão escritos.
   - Decision: if `.decisionssearch/` já existe → sugerir `decisionssearch-update` e STOP.
2. **Verificar MCP** — `memory.query` trivial (qualquer termo, limit 1).
   - Decision: if falha → mostrar instruções de setup do servidor DecisionsSearch e STOP.
3. **Q&A em funil** — uma pergunta por vez, múltipla escolha quando possível, sempre confirmando o que foi inferido no passo 1 em vez de perguntar do zero: setor → empresa/produto → escopo do sistema → domínios & módulos → macro-regras.
   Exemplo preenchido (ExampleProject): setor "construção civil" → produto "sistema de propostas de fundações" → escopo "propostas comerciais de estacas, do dimensionamento ao PDF" → domínios `[fundações, comercial]`, módulos `[propostas, estacas, cargas]` → macro-regra "Toda proposta exige carga admissível calculada antes de aprovação".
4. **Draft dos 3 arquivos** — preencher `assets/business-template.md`, `assets/architecture-template.md`, `assets/code-patterns-template.md` com detecção + respostas.
5. **Self-Refine gate** — rascunhe os 3 arquivos e critique contra:
   - Taxonomia tem ≥2 domínios e ≥3 módulos confirmados pelo usuário?
   - TL;DRs com ≤5 bullets e cada arquivo ≤150 linhas?
   - Macro-regras em linguagem estável, livre de implementação transitória?
   - Nada inventado que o usuário não confirmou?
   Refine até as 4 respostas serem "sim"; só então mostre o preview.
6. **Preview + confirmação** — mostrar os 3 arquivos completos + `state.json` (de `assets/state-template.json`, com timestamps atuais); gravar `.decisionssearch/` apenas com "sim" explícito.
7. **Instalar skills** — copiar os diretórios da fonte canônica `skills-memory/` (exceto `_template/` e `decisionssearch-init/`) para `.claude/skills/` do projeto.
   - Decision: if skill homônima já existe em `.claude/skills/` → perguntar antes de sobrescrever.
8. **Registrar projeto no grafo** — `graph.project.create` (ou `memory.manual.create` de nó Project, conforme API disponível no servidor).
9. **Oferecer seed** — propor gravar as macro-regras levantadas como primeiras memórias `BusinessRule` via `create-business-rule-memory` (cada uma com preview próprio).
10. **Mini-tutorial de encerramento** — imprimir o fluxo de uso: fim de PR → `decisionssearch-capture`; dúvida de regra → `rule-blame`; por que o código é assim → `code-blame`; por que a arquitetura é assim → `architecture-blame`; busca geral → `query-memory`; sincronizar docs → `decisionssearch-update`.

## Output Schema

```yaml
files_created: [path]
skills_installed: [name]
project_node_id: string
seed_rules_created: [memory_id]
```

### Example

```yaml
files_created:
  - .decisionssearch/business.md
  - .decisionssearch/architecture.md
  - .decisionssearch/code-patterns.md
  - .decisionssearch/state.json
skills_installed:
  - decisionssearch-capture
  - decisionssearch-update
  - create-pr-memory
  - create-business-rule-memory
  - create-architectural-decision-memory
  - create-code-pattern-memory
  - capture-reasoning
  - link-pr-to-memory
  - query-memory
  - rule-blame
  - architecture-blame
  - code-blame
project_node_id: "proj_example-project_01"
seed_rules_created:
  - "mem_a1b2c3"  # "Toda proposta exige carga admissível calculada antes de aprovação"
```

## Verification

- [ ] `test -f .decisionssearch/business.md && test -f .decisionssearch/architecture.md && test -f .decisionssearch/code-patterns.md && test -f .decisionssearch/state.json`
- [ ] `ls .claude/skills/ | grep -cE 'decisionssearch|memory|blame|reasoning'` ≥ 10
- [ ] `memory.query` pelo nome do projeto retorna o nó criado
- [ ] Output bate com o schema (todos os campos, tipos certos)

## Anti-patterns

- Do NOT perguntar setor, produto ou linguagem se o README/CLAUDE.md já diz — confirme o inferido.
- Do NOT inventar domínios ou módulos que o usuário não confirmou explicitamente.
- Do NOT gravar taxonomia vazia ou com placeholder — sem taxonomia não há captura consistente depois.
- Do NOT despejar todas as perguntas de uma vez — o funil é uma pergunta por vez.

## Failure modes & recovery

- **MCP DecisionsSearch indisponível** → STOP no passo 2, com instruções de setup. Nunca criar `.decisionssearch/` sem grafo funcionando.
- **Usuário abandona o Q&A no meio** → não gravar nada parcial; resumir o que já foi respondido para retomar depois.
- **Skill homônima já instalada em `.claude/skills/`** → perguntar antes de sobrescrever; nunca substituir silenciosamente.

## RECAP

- Detecte antes de perguntar; confirme o inferido em vez de re-perguntar.
- Nunca grave `.decisionssearch/` sem preview e confirmação explícita.
- A taxonomia de domínios/módulos gravada aqui é a fonte oficial de `domain`/`modules` de todas as capturas futuras.
