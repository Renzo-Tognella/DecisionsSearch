---
name: decisionssearch-capture
description: "Orquestra a captura completa de memórias no fim de um PR: sweep único da sessão+PR, triagem confirmada, roda as skills de captura e linka tudo. Use quando o usuário disser 'fecha o PR capturando as memórias', 'decisionssearch capture', 'popula a memória desse PR', ao finalizar um PR. Do NOT use for capturas avulsas de uma classe só — use a skill `create-*` específica; nem para configurar o projeto — use `decisionssearch-init`."
version: 1.0.0
metadata:
  decisionssearch:
    memory_class: none
    context_file: .decisionssearch/business.md
    related_skills: [create-pr-memory, capture-reasoning, create-business-rule-memory, create-architectural-decision-memory, create-code-pattern-memory, link-pr-to-memory, decisionssearch-update]
---

# DecisionsSearch Capture

Você é a orquestradora de fim-de-PR: um sweep, uma triagem, um preview consolidado — e o grafo ganha PR, reasoning, regras, decisões, padrões e links de uma vez, sem seis confirmações sequenciais.

**CORE RULE:** Um sweep, uma triagem confirmada, um preview consolidado, links por último. Nunca rode skill filha sem a triagem aprovada.

## When to activate

- Trigger phrases: "decisionssearch capture", "fecha o PR capturando as memórias", "popula a memória desse PR"
- Contexts: PR finalizado (aberto pra merge ou mergeado) ao fim de uma sessão de trabalho

**Do NOT activate for:**
- captura avulsa de uma classe só ("registra essa regra") → use a skill `create-*` específica
- projeto sem `.decisionssearch/` → use `decisionssearch-init`
- sincronizar os documentos com o grafo → use `decisionssearch-update`

## Inputs

- `pr` (optional, default: PR do branch atual via `gh pr view`): número ou URL do PR.
- Aprovações do usuário: triagem (passo 4) e preview consolidado (passo 6).

## Context load

- Carregar os 3 arquivos `.decisionssearch/` (business, architecture, code-patterns).
- Se `.decisionssearch/` não existir → sugerir `decisionssearch-init` e STOP.
- Verificar MCP DecisionsSearch com um `memory.query` trivial antes de qualquer escrita.

## Procedure

1. **Pré-condições** — `.decisionssearch/` existe; MCP responde; PR identificado (`gh pr view` do branch atual ou o número dado).
   - Decision: if qualquer uma falha → STOP com a instrução correspondente (init / setup MCP / informar o PR).
2. **Sweep único → session digest** — coletar numa passada: diff do PR (`gh pr view --json title,number,url,state,author,files,createdAt,mergedAt,headRefName,body` + `gh pr diff`), plano/tasks da sessão, decisões tomadas com alternativas descartadas, erros/correções de rota. Formato:
   ```yaml
   digest:
     pr: {number, title, url, files, dates, authors}
     plan: [passos como executados]
     decisions: [{choice, alternatives: [{option, why_rejected}], justification}]
     rules_touched: [candidatas a BusinessRule]
     patterns_introduced: [candidatas a CodePattern]
   ```
   - Reason: `capture-reasoning` e `create-architectural-decision-memory` consomem o MESMO digest — a varredura acontece 1x, não 2x.
3. **Carregar contexto** — os 3 arquivos `.decisionssearch/` (taxonomia, decisões vigentes, padrões vigentes) para as triagens do passo 4.
4. **Triagem** — aplicar a tabela e apresentar o resultado ANTES de rodar qualquer condicional:

   | Skill filha | Roda quando |
   |---|---|
   | `create-pr-memory` | SEMPRE |
   | `capture-reasoning` | SEMPRE |
   | `create-business-rule-memory` | digest menciona regra de domínio nova/alterada OU diff toca validação/policy/workflow OU vocabulário do `business.md` aparece em mudança semântica |
   | `create-architectural-decision-memory` | digest tem escolha com alternativas descartadas OU diff toca stack/estrutura/integração |
   | `create-code-pattern-memory` | diff introduz convenção repetível divergente/complementar ao `code-patterns.md` |

   Apresentar: "Detectei: [lista com justificativa 1-linha cada]. Confirma a triagem? (adicione/remova)".
   - Decision: aguardar aprovação; usuário pode adicionar/remover skills da lista.
5. **Executar filhas criadoras em `mode: orchestrated`** — passar o digest a `create-pr-memory`, as `create-business-rule-memory`/`create-architectural-decision-memory`/`create-code-pattern-memory` aprovadas; cada uma roda seu procedimento com Self-Refine interno e devolve o DRAFT, SEM persistir.
6. **Preview consolidado (Self-Refine da orquestradora)** — antes de mostrar, criticar o conjunto: alguma memória duplica outra do lote? links propostos cobrem todos os nós novos? classes certas (regra vs AD vs pattern)? Então apresentar TODAS as memórias candidatas + links propostos num bloco único; o usuário aprova em lote ou edita item a item.
7. **Persistir na ordem** — (a) todos os nós `MemoryItem` (`create-pr-memory`, `create-business-rule-memory`, `create-architectural-decision-memory`, `create-code-pattern-memory`); (b) `capture-reasoning` por último entre os criadores, passando os ids recém-criados em `related_memory_ids` (episódio referencia os nós, não o contrário); (c) `link-pr-to-memory` com a lista consolidada de links entre `MemoryItem`s — nunca link órfão.
8. **Verificar** — `memory.get`/`memory.episode.query` de cada id criado; arestas confirmadas pela verificação do `link-pr-to-memory`.
9. **Fechamento** — if ≥1 AD ou CodePattern novo → sugerir `decisionssearch-update` ("N candidatos a sync nos documentos").

## Output Schema

```yaml
pr_memory_id: memory_id
episode_id: memory_id
business_rules: [memory_id]
decisions: [memory_id]
patterns: [memory_id]
links: [{from: memory_id, to: memory_id, type: enum}]   # apenas entre MemoryItems (PR/regra/decisão/padrão)
update_suggested: bool
```

### Example

```yaml
pr_memory_id: "prm_example-project_41"
episode_id: "epi_task_pile_01"   # criado com related_memory_ids: ["prm_example-project_41", "mem_pile_rule_01"]
business_rules: ["mem_pile_rule_01"]
decisions: []
patterns: ["cp_domain_validation_services"]
links:
  - {from: "prm_example-project_41", to: "mem_pile_rule_01", type: IMPLEMENTS}
  - {from: "prm_example-project_41", to: "cp_domain_validation_services", type: EVIDENCES}
update_suggested: true
```

## Verification

- [ ] `memory.get` de cada `MemoryItem` do output retorna o nó; `memory.episode.query` confirma o `episode_id`
- [ ] `link-pr-to-memory` reportou `links_verified == len(links)`
- [ ] Nenhuma filha persistiu antes do preview consolidado aprovado
- [ ] Nenhum anti-pattern abaixo foi disparado

## Anti-patterns

- Do NOT rodar as 5 filhas incondicionalmente — a triagem existe para evitar memória-lixo.
- Do NOT pedir 6 confirmações sequenciais — o preview é consolidado; confirmações são 2 (triagem + lote).
- Do NOT linkar antes de todos os nós existirem.
- Do NOT re-varrer a sessão em cada filha — o digest é único e compartilhado.

## Failure modes & recovery

- **MCP DecisionsSearch indisponível** → STOP antes de qualquer coisa; nada é criado pela metade por padrão de entrada.
- **Skill filha falha no meio da persistência** → reportar exatamente o que persistiu (ids) e o que não; retomar do ponto sem duplicar nós já criados.
- **MCP cai no meio da persistência** → STOP com estado parcial documentado (ids criados, links pendentes); ao retomar, começar pela verificação dos ids listados.
- **`capture-reasoning` falha ao persistir o episódio** → as demais memórias já criadas permanecem; reportar a lacuna no output (sem `episode_id`).

## RECAP

- Um sweep → um digest compartilhado; triagem confirmada antes de qualquer filha.
- Preview consolidado: o usuário aprova o lote, não 6 diálogos.
- Nós primeiro, links por último, tudo verificado com `memory.get`.
