---
name: decisionssearch-update
description: "Sincroniza os documentos .decisionssearch/ com as memórias novas do grafo desde o último sync: sintetiza, propõe diff, grava após aprovação. Use quando o usuário disser 'decisionssearch update', 'atualiza o business.md', 'sincroniza os docs com a memória', ou quando a `decisionssearch-capture` sugerir. Do NOT use for configurar projeto novo — use `decisionssearch-init`; nem para capturar memórias — use `decisionssearch-capture`."
version: 1.0.0
metadata:
  decisionssearch:
    memory_class: none
    context_file: .decisionssearch/business.md
    related_skills: [decisionssearch-init, decisionssearch-capture, architecture-blame]
---

# DecisionsSearch Update

Você mantém os documentos `.decisionssearch/` como projeção fiel do grafo: o que foi capturado como memória desde o último sync vira atualização proposta nos docs — nunca gravada sem o usuário ver o diff.

**CORE RULE:** Síntese + diff proposto + aprovação — nunca grave `.decisionssearch/` sem o usuário ver o diff.

## When to activate

- Trigger phrases: "decisionssearch update", "sincroniza os docs com a memória", "atualiza o business.md/architecture.md/code-patterns.md"
- Contexts: `decisionssearch-capture` sugeriu sync (ADs/patterns novos); documentos visivelmente defasados do grafo

**Do NOT activate for:**
- projeto sem `.decisionssearch/` → use `decisionssearch-init`
- capturar memórias novas → use `decisionssearch-capture`
- consultar timeline de decisão → use `architecture-blame`

## Inputs

- Nenhum obrigatório. `files` (optional, default: os 3): subconjunto de documentos a sincronizar.

## Context load

- Carregar os 3 arquivos `.decisionssearch/` + `state.json`.
- Se `.decisionssearch/` não existir → sugerir `decisionssearch-init` e STOP.
- Verificar MCP DecisionsSearch com um `memory.query` trivial.

## Procedure

1. **Ler o estado** — `state.json.last_synced_at` e `skills_version`.
2. **Buscar memórias novas** — `memory.query` por classe com `event_date > last_synced_at`: BusinessRule → `business.md` (macro-regras, glossário, taxonomia), ArchitecturalDecision → `architecture.md` (tabela "Decisões vigentes"), CodePattern → `code-patterns.md` (padrões vigentes, anti-padrões).
   - Decision: if 0 memórias novas → informar "nada a sincronizar" e (com confirmação) atualizar só o timestamp; fim.
3. **Sintetizar o diff por arquivo** — para cada memória nova, a mudança proposta: adicionar linha na tabela de decisões, nova macro-regra, padrão novo, marcação de substituído (AD com aresta `DEPRECATES` de entrada, i.e. outra AD aponta `(nova)-[:DEPRECATES]->(esta)` → linha antiga sai, nova entra).
   - Decision: if memória nova CONTRADIZ o documento (ex.: decisão vigente no doc foi deprecada no grafo) → perguntar qual vale (única interação além da aprovação final); a resposta pode gerar correção no doc ou aviso de memória a corrigir.
4. **Self-Refine gate** — rascunhe os diffs e critique contra:
   - Arquivos continuam ≤150 linhas e com TL;DR correto após o diff?
   - Taxonomia consistente (nenhum domínio/módulo órfão ou duplicado)?
   - Cada mudança rastreável a um memory_id?
   - Nenhuma seção reescrita além do necessário (diff mínimo)?
   Refine até as 4 respostas serem "sim"; só então mostre o diff.
5. **Preview + confirmação** — mostrar diff unificado por arquivo; gravar apenas com "sim" explícito.
6. **Gravar e registrar** — aplicar os diffs aprovados + `state.json.last_synced_at = now`.
7. **De carona: versão das skills** — if `state.json.skills_version` < versão da fonte canônica (`skills-memory/`) → oferecer reinstalar as skills atualizadas em `.claude/skills/`.

## Output Schema

```yaml
files_updated: [path]
memories_synced: int
conflicts_resolved:
  - memory_id: string
    resolution: doc_updated | memory_flagged
skills_upgraded: bool
new_last_synced_at: ISO 8601
```

### Example

```yaml
files_updated:
  - .decisionssearch/architecture.md
  - .decisionssearch/code-patterns.md
memories_synced: 3
conflicts_resolved:
  - memory_id: "adm_blend_alpha_04"
    resolution: doc_updated   # tabela de decisões: substituiu a linha da fusão RRF simples
skills_upgraded: false
new_last_synced_at: "2026-07-04T15:00:00Z"
```

## Verification

- [ ] `git diff .decisionssearch/` (ou diff dos arquivos) corresponde exatamente ao preview aprovado
- [ ] `state.json.last_synced_at` atualizado e ≥ `event_date` de todas as memórias sincronizadas
- [ ] Cada mudança gravada rastreia a um memory_id existente
- [ ] Nenhum anti-pattern abaixo foi disparado

## Anti-patterns

- Do NOT reescrever seções inteiras — o diff é mínimo, cirúrgico, rastreável a memórias.
- Do NOT resolver contradição doc×grafo sozinho — é decisão do usuário.
- Do NOT atualizar o timestamp sem ter sincronizado (ou sem confirmação no caso "nada a sincronizar").
- Do NOT deixar os arquivos crescerem além de ~150 linhas — condensar antes de adicionar.

## Failure modes & recovery

- **MCP DecisionsSearch indisponível** → STOP, informe o usuário com instrução de setup.
- **Conflito não resolvido pelo usuário** → não gravar AQUELE arquivo; gravar os demais aprovados e listar o pendente.
- **`state.json` corrompido/ausente** → tratar como primeiro sync: propor reconstrução com `last_synced_at` escolhido pelo usuário (ou epoch), nunca chutar.

## RECAP

- Nunca grave sem diff aprovado; diff mínimo e rastreável a memory_ids.
- Contradição doc×grafo = pergunta ao usuário, não decisão sua.
- Timestamp só avança com sync real (ou confirmação explícita).
