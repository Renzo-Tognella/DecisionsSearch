# DecisionsSearch Skills Suite v2

Fonte canônica das skills de memória do DecisionsSearch. A instalação num projeto consumidor é feita pela `decisionssearch-init`, que copia as skills para `.claude/skills/` do projeto e cria os arquivos de contexto `.decisionssearch/`.

## Fluxo

```text
                       ┌──────────────────┐
  1x por projeto ────► │  decisionssearch-init  │──► .decisionssearch/{business,architecture,code-patterns}.md + state.json
                       └──────────────────┘    + skills instaladas + nó Project no grafo
                                │
        fim de PR               ▼
       ┌────────────────────────────────────────────┐
       │ decisionssearch-capture (orquestradora)          │
       │  sweep único → digest → triagem confirmada │
       │  ├─ create-pr-memory        (sempre)       │
       │  ├─ capture-reasoning       (sempre)       │
       │  ├─ create-business-rule-memory   (cond.)  │
       │  ├─ create-architectural-decision-memory   │
       │  ├─ create-code-pattern-memory    (cond.)  │
       │  └─ link-pr-to-memory       (por último)   │
       └────────────────────────────────────────────┘
                                │  sugere quando há ADs/patterns novos
                                ▼
                       ┌──────────────────┐
                       │ decisionssearch-update │──► diff proposto → docs .decisionssearch/ sincronizados
                       └──────────────────┘

  consulta:  query-memory (busca geral, incl. episódios de reasoning)
             rule-blame · architecture-blame · code-blame (timelines de cadeia)
```

## Inventário

| Skill | Classe | Quando usar | Related |
|-------|--------|-------------|---------|
| `decisionssearch-init` | — | configurar projeto novo (1x) | update, capture |
| `decisionssearch-capture` | — | fim de PR: captura orquestrada | todas as create-*, link |
| `decisionssearch-update` | — | sincronizar `.decisionssearch/` com o grafo | init, capture |
| `create-pr-memory` | PRMemory + FeatureDescription derivada | PR/diff/Git → memória operacional com todos os arquivos, objetivo e resumo em prosa | capture, link |
| `create-business-rule-memory` | BusinessRule | regra de domínio durável | rule-blame |
| `create-architectural-decision-memory` | ArchitecturalDecision | decisão com alternativas | architecture-blame, capture-reasoning |
| `create-code-pattern-memory` | CodePattern | padrão reutilizável com evidência explícita | code-blame, update |
| `capture-reasoning` | Episode | processo/plano da task → memória episódica | AD, query-memory |
| `link-pr-to-memory` | — | links tipados entre nós (passo final da captura) | capture |
| `query-memory` | — | busca semântica geral ("já fizemos algo assim?") | blames |
| `rule-blame` | — | timeline de uma regra | query-memory |
| `architecture-blame` | — | timeline de uma decisão | query-memory, update |
| `code-blame` | — | busca exata por arquivo → reranking pelo resumo/objetivo → razão | query-memory, create-pr |

## Padrão das skills

Toda skill segue [`_template/SKILL-TEMPLATE.md`](_template/SKILL-TEMPLATE.md): frontmatter-contrato (triggers em aspas + "Do NOT use for"), CORE RULE no topo, procedure ReAct numerado, Self-Refine gate antes de persistir/apresentar, Output Schema com exemplo preenchido, Verification executável, ≥3 anti-patterns, failure modes com recovery, RECAP no fim.

**Pré-requisito para skill nova ou edição:** passar em [`_template/audit.sh`](_template/audit.sh):

```bash
skills-memory/_template/audit.sh skills-memory/<skill-dir>
```

Cada skill tem `golden-set.md` (5 canônicos + 3 anti-canônicos + 2 ambíguos) — base do smoke-test pós-edição e do loop de otimização (SkillOpt: editar 1 seção por iteração, medir no golden-set, aceitar só se melhorar).

## Contrato operacional atual

- `PRMemory` é a memória operacional de Git Blame: leia PR, diff e histórico; preserve todos os arquivos alterados e escreva objetivo, summary e efeito em prosa.
- `FeatureDescription` é uma narrativa rica derivada dentro de PRMemory, com trigger, stakeholders, files, rules e action triggers. Não é um nó separado nem um campo Python novo.
- Para perguntas com arquivo, a ordem é busca exata em changed_files e depois reranking pela aderência ao summary/objetivo do PR. Busca semântica ampla é apenas fallback controlado.
- `BusinessRule` e `ArchitecturalDecision` são prosa estável, independente da implementação; PRs, arquivos e diffs são evidências e links.
- `CodePattern` só existe quando há evidência explícita de reutilização/padronização ou repetição verificável. Uma ocorrência isolada permanece em PRMemory.
- Toda persistência, depreciação ou link continua exigindo preview, confirmação explícita e verificação posterior.

[`golden-set-consolidated.md`](golden-set-consolidated.md) agrega os 130 prompts das 13 skills numa bateria única, focada em **roteamento cruzado**: colisões onde o mesmo prompt (ou muito parecido) é canônico numa skill e anti-canônico/ambíguo em outra. Rodar com as 13 skills instaladas juntas — é o teste mais informativo da suíte e o primeiro a rodar na validação real (Task 17).

## Convenções de grafo

Duas APIs de relação, verificadas contra o servidor real (`server/tools.py`) — nunca misturar:
- **PR → MemoryItem** (`memory.pr.link_memory`): `IMPLEMENTS`, `EVIDENCES`, `MODIFIES`.
- **MemoryItem → MemoryItem** (`memory.link`): `RELATED_TO`, `DEPENDS_ON`, `REFINES`, `DEPRECATES`, `CONFLICTS_WITH`, `EVOLVES_FROM` (último recurso: `RELATED_TO`).
- Substituição com deprecação (regra/decisão superada) é `memory.deprecate(memory_id, replaced_by, rationale)` — não um `memory.link` manual; produz `(nova)-[:DEPRECATES]->(antiga)`.
- `modules`/`domain` de toda memória vêm da taxonomia do `.decisionssearch/business.md` do projeto.
- AD vs reasoning: decisão durável com alternativas → `ArchitecturalDecision` (`memory.manual.create`); processo da task → episódio (`memory.episode.create`). Episódios não são `MemoryItem` — não passam por `memory.link`; a conexão com outras memórias é `related_memory_ids` na própria criação do episódio.
