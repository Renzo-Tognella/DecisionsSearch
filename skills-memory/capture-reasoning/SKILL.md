---
name: capture-reasoning
description: "Varre a sessão e extrai o registro de reasoning da task (objetivo, abordagem, alternativas/lições, resultado) como memória episódica. Use quando o usuário disser 'captura o reasoning dessa task', 'salva o plano e as decisões dessa sessão', ao fechar um card, ou como passo sempre-roda da `decisionssearch-capture`. Do NOT use for decisões arquiteturais duráveis — use `create-architectural-decision-memory`; nem para buscar reasoning de tasks passadas — use `query-memory`."
version: 1.0.0
metadata:
  decisionssearch:
    memory_class: Episode
    context_file: .decisionssearch/business.md
    related_skills: [decisionssearch-capture, create-architectural-decision-memory, query-memory]
---

# Capture Reasoning

Você é o analisador de reasoning da sessão: preserva o PROCESSO de decisão de uma task — plano, tentativas, porquês de percurso — para que uma task parecida no futuro recupere "como resolvemos da última vez".

**CORE RULE:** Capture o PROCESSO (abordagem, tentativas, porquês de percurso), não o artefato. Nunca persista sem preview e confirmação.

## When to activate

- Trigger phrases: "captura o reasoning dessa task", "salva o plano e as decisões dessa sessão", "registra como resolvemos esse card"
- Contexts: fechamento de card/task; passo sempre-roda da `decisionssearch-capture`

**Do NOT activate for:**
- decisão durável com alternativas (tecnologia, estrutura) → use `create-architectural-decision-memory`
- buscar reasoning de tasks passadas ("já fizemos algo assim?") → use `query-memory`
- criar memória do PR em si → use `create-pr-memory`

## Inputs

- `mode` (optional, default: `standalone`): `standalone` (faz o sweep da sessão) | `orchestrated` (recebe `digest` pronto da `decisionssearch-capture` e pula o sweep).
- `digest` (required se `mode: orchestrated`): session digest com plano/decisões/alternativas já extraídos.
- `related_memory_ids` (optional): ids de memórias já criadas na mesma captura (ex.: a PRMemory, uma AD) para vincular ao episódio no momento da criação.

## Context load

- Carregar `.decisionssearch/business.md` (taxonomia para contextualizar objetivo/tags).
- Se o arquivo não existir → sugerir `decisionssearch-init` e STOP.
- Verificar MCP DecisionsSearch com um `memory.query` trivial antes de qualquer escrita.

## Procedure

1. **Obter o digest** — em `mode: orchestrated`, receber pronto. Em `standalone`, varrer a sessão: plano/tarefas (TodoWrite, plano aprovado), decisões tomadas, alternativas descartadas no percurso, erros e correções de rota, resultado final.
   - Reason: o registro cobre a task inteira, não só o final feliz.
2. **Estruturar o registro** — mapear para os campos reais de `memory.episode.create`: `task_description` (objetivo + contexto em 1-2 frases), `approach` (o plano/decisão central como foi executado, incluindo alternativas descartadas e o porquê — tudo em texto corrido), `outcome` (`completed` | `failed` | `partial`), `lessons` (lista de aprendizados/porquês específicos, um por item), `tags` (módulos/domínio envolvidos).
3. **Vincular memórias relacionadas** — se, na mesma captura, uma `create-architectural-decision-memory` ou `create-pr-memory` já criou nó(s), incluir os ids em `related_memory_ids` no momento da criação do episódio.
   - Reason: episódios (`EpisodicMemory`) não são `MemoryItem` — `memory.link` não os alcança. O único jeito de conectar um episódio a outra memória é via `related_memory_ids` na própria criação, não um link separado depois.
   - Decision: if o digest tem uma decisão durável com alternativas (escolha de tecnologia/estrutura) → sugerir também `create-architectural-decision-memory`; se criada, referenciar seu id aqui.
4. **Self-Refine gate** — rascunhe o registro completo e critique contra:
   - Todos os campos obrigatórios preenchidos (sem string vazia)?
   - Uma task futura parecida consegue REUSAR esta abordagem? (específica o bastante, sem jargão de sessão)
   - `task_description` + `approach` descrevem a task sem depender do contexto da conversa? (são o alvo da busca semântica)
   - Episódio parecido buscado (`memory.episode.query` com `project`/`tag`)?
   Refine até as 4 respostas serem "sim"; só então mostre o preview.
5. **Preview + confirmação** — mostrar o registro completo; persistir apenas com "sim" explícito.
6. **Persistir** — `memory.episode.create` com os campos do passo 2 + `related_memory_ids` do passo 3.

## Output Schema

```yaml
# project is optional; omit it to use the current workspace folder
task_description: string      # embedding alvo, junto com approach
approach: string               # plano executado + alternativas descartadas + porquês
outcome: completed | failed | partial
lessons: [string]
related_memory_ids: [memory_id]
tags: [string]
```

### Example

```yaml
# project omitted: DecisionsSearch derives it from the current workspace folder
task_description: "Corrigir o primeiro estágio de retrieval, que retornava resultados irrelevantes para queries curtas."
approach: "Reproduzido com o golden-set de recall; isolado o estágio denso (cosine relevance sem fusão) e identificada normalização ausente no ranking. Alternativa descartada: aumentar top_k do estágio denso e filtrar depois — mascarava o problema em vez de corrigi-lo. Adotado RRF ponderado na fusão para preservar o ganho quando os dois sinais discordam."
outcome: completed
lessons:
  - "Erro estava no ranking do primeiro estágio (normalização), não na fusão"
  - "Pendente: re-tuning dos pesos do RRF por corpus"
related_memory_ids: ["adm_blend_alpha_04"]
tags: [retrieval, ranking]
```

## Verification

- [ ] `memory.episode.query` com `project` retorna o episódio recém-criado
- [ ] `related_memory_ids` reflete o que foi de fato considerado na sessão (não inventado)
- [ ] Output bate com o schema (`outcome` é um dos 3 valores válidos)
- [ ] Nenhum anti-pattern abaixo foi disparado

## Anti-patterns

- Do NOT capturar só o resultado final — o valor está no percurso (plano, tentativas, correções) dentro de `approach`/`lessons`.
- Do NOT tentar linkar o episódio a outra memória via `memory.link` — episódios não são `MemoryItem`; use `related_memory_ids` na criação.
- Do NOT escrever o registro com referências que só fazem sentido dentro desta conversa ("como discutido acima").
- Do NOT usar um valor de `outcome` fora de `completed`/`failed`/`partial`.

## Failure modes & recovery

- **MCP DecisionsSearch indisponível** → STOP, informe o usuário com instrução de setup. Nunca "persista depois".
- **Sessão sem plano/decisões rastreáveis** (ex.: task trivial) → dizer isso e perguntar se vale registrar mesmo assim; registro vazio não é criado.
- **`related_memory_ids` aponta para id que não existe** → remover o id inválido do payload e avisar, nunca persistir referência quebrada.

## RECAP

- Processo, não artefato: `approach` + `lessons` carregam o percurso, não só o resultado.
- Vínculo com outras memórias é `related_memory_ids` na criação — nunca `memory.link` (tipos de nó diferentes).
- Nunca persista sem preview/confirmação; `outcome` restrito ao enum do servidor.
