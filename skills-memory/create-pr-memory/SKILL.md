---
name: create-pr-memory
description: "Transforma um pull request em PRMemory operacional, baseada em Git Blame, com todos os arquivos alterados, objetivo e resumo em prosa. Use quando o usuário disser 'cria a memória desse PR', 'salva o PR #N na memória' ou como passo sempre-roda da `decisionssearch-capture`. Do NOT use para regra de negócio sem PR — use `create-business-rule-memory`; decisão — use `create-architectural-decision-memory`; padrão reutilizável — use `create-code-pattern-memory`."
version: 1.1.0
metadata:
  decisionssearch:
    memory_class: PRMemory
    feature_description: "narrativa derivada, não um nó separado"
    context_file: .decisionssearch/business.md
    related_skills: [decisionssearch-capture, link-pr-to-memory, create-business-rule-memory, create-architectural-decision-memory]
---

# Create PR Memory

Você cria uma memória operacional de Git Blame para um PR: o que mudou, qual era o objetivo, quais arquivos foram alterados, quem é afetado, que regras aparecem e quais ações o comportamento dispara. A memória deve continuar útil quando o diff já não estiver aberto.

**CORE RULE:** Leia o PR, o diff e o histórico real (`gh` + Git) antes de sintetizar. `changed_files` é sempre a lista completa de arquivos alterados. Nunca persista sem preview e confirmação explícita.

## When to activate

- Trigger phrases: "cria a memória desse PR", "salva o PR #N na memória", "registra esse PR no decisionssearch"
- Contexts: PR aberto ou mergeado que deve virar memória; passo sempre-roda da `decisionssearch-capture`

**Do NOT activate for:**

- regra de domínio sem PR específico → use `create-business-rule-memory`
- decisão de design/arquitetura → use `create-architectural-decision-memory`
- padrão reutilizável explicitamente evidenciado → use `create-code-pattern-memory`
- consultar PRs existentes → use `query-memory`

## Inputs

- `pr` (required): número, URL ou branch do PR. Fonte: usuário ou sessão.
- `mode` (optional, default: `standalone`): `standalone` (coleta própria via `gh` e Git) | `orchestrated` (recebe `digest` pronto da `decisionssearch-capture` e ainda valida a evidência antes de escrever).
- `digest` (required se `mode: orchestrated`): digest com o PR e as evidências já coletadas.

## Context load

- Carregar `.decisionssearch/business.md`; a taxonomia é a fonte oficial para `areas`/`modules`.
- Se o arquivo não existir → sugerir `decisionssearch-init` e STOP.
- Verificar MCP DecisionsSearch com um `memory.query` trivial antes de qualquer escrita.

## Contrato PRMemory + FeatureDescription

`FeatureDescription` é uma narrativa rica derivada do PR, não um novo tipo de nó ou campo Python. Ela deve existir no preview e ser materializada nos campos suportados por `PRMemory`: a narrativa no `summary`, o objetivo em prosa dentro do resumo e/ou `work_item_summary`, todos os caminhos em `changed_files`, e as classificações em `areas`.

```yaml
feature_description:
  narrative: string          # um parágrafo coeso, não uma lista de fragmentos
  trigger: string            # evento, condição ou intenção que ativa a feature
  stakeholders: [string]     # usuários, sistemas, equipes ou papéis afetados
  files: [path]              # exatamente a lista completa de changed_files
  rules: [string]            # regras observadas; IDs só quando existirem
  action_triggers: [string]  # condição → ação/efeito observável
```

Regras do contrato:

- `narrative`, `summary` e `work_item_summary` são prosa operacional: objetivo + mudança + efeito, sem apenas repetir o título.
- `trigger`, `stakeholders`, `rules` e `action_triggers` só podem ser extraídos de PR, diff, histórico, work item ou digest; ausência vira lacuna ou pergunta, nunca invenção.
- `files` deve conter todos os caminhos repo-relativos, incluindo testes, migrações, configuração e documentação.
- `FeatureDescription` não deve ser enviado como campo extra para `memory.pr.create`; antes da chamada, incorporar a narrativa nos campos suportados.

## Procedure

1. **Coletar a fonte primária** — executar `gh pr view <pr> --json title,number,url,state,author,files,createdAt,mergedAt,headRefName,body` e `gh pr diff <pr> --name-only`; confirmar a lista com `git show --stat --format=fuller <pr>` ou o commit de merge.
   - Em modo `orchestrated`, usar o digest, mas conferir a lista contra o checkout e o PR real quando `gh` estiver disponível.
   - Se `gh` falhar, não preencher de memória humana; seguir os failure modes.
2. **Reconstruir o Git Blame operacional** — para cada arquivo alterado, usar `git log --follow --oneline -- <path>` e, quando a motivação precisar de contexto, `git blame -L <range> -- <path>` seguido do commit/PR correspondente. O objetivo é explicar a razão da mudança, não responder autoria de linha.
3. **Construir a FeatureDescription** — escrever a narrativa em prosa e preencher trigger, stakeholders, arquivos, regras e action triggers. Objetivo e efeito operacional devem aparecer explicitamente no `summary`; todos os arquivos devem aparecer em `changed_files`.
4. **Classificar sem extrapolar** — inferir `areas`/`modules` somente pela taxonomia do `business.md` e pelas evidências. Uma regra ou decisão pode ser citada na narrativa, mas só vira `BusinessRule`/`ArchitecturalDecision` em skill própria. Um único exemplo não vira `CodePattern`.
5. **Buscar duplicatas e relacionados** — primeiro `memory.pr.query` por `project`, `repo`, `pr_number` e arquivo; depois buscar regras/decisões/padrões pelos termos do `summary` e do objetivo. Apresentar candidatos com a evidência e a relação proposta; não criar links automaticamente.
6. **Self-Refine gate** — criticar o rascunho contra:
   - `changed_files` é completo e repo-relativo?
   - `summary` explica objetivo, mudança e efeito em prosa?
   - `feature_description` tem trigger, stakeholders, arquivos, regras e action triggers, sem fatos inventados?
   - `git log`/`git blame`/PR sustentam cada razão; lacunas estão marcadas?
   - todos os campos obrigatórios estão preenchidos ou foram perguntados?
   Refine até todas as respostas serem "sim"; só então mostrar o preview.
7. **Preview + confirmação** — mostrar o FeatureDescription e o payload completo que será enviado a `memory.pr.create`; persistir somente após "sim" explícito.
8. **Persistir e verificar** — executar `memory.pr.create`; confirmar `memory.pr.query` por `project`, `repo` e `pr_number`. Links confirmados ficam para `link-pr-to-memory` ou para o fechamento da `decisionssearch-capture`.

## Output Schema

```yaml
feature_description:
  narrative: string
  trigger: string
  stakeholders: [string]
  files: [path]
  rules: [string]
  action_triggers: [string]
payload:
  # project is optional; omit it to use the current workspace folder
  repo: string
  pr_number: int
  title: string
  summary: string          # objetivo + mudança + efeito, em prosa
  changed_files: [path]    # lista completa
  areas: [string]
  pr_url: string
  work_item_url: string
  work_item_summary: string
  event_date: ISO 8601
  authors: [string]
  branch: string
  status: open | merged | closed
```

### Example

```yaml
feature_description:
  narrative: "Quando uma proposta informa um tipo de estaca incompatível com a carga admissível, o fluxo passa a bloquear a criação e informar o motivo ao usuário; a mudança envolve o serviço de propostas, o modelo de domínio e o formulário frontend, afetando engenharia, operações comerciais e suporte."
  trigger: "criação ou aprovação de proposta com PileType incompatível com a carga admissível"
  stakeholders: ["engenharia", "operações comerciais", "usuários do formulário de proposta", "suporte"]
  files:
    - services/proposal_service.py
    - models/pile_type.py
    - frontend/src/components/ProposalForm.tsx
    - spec/services/proposal_service_spec.rb
  rules:
    - "Propostas não podem prosseguir quando a capacidade nominal da estaca é menor que a carga admissível."
  action_triggers:
    - "Se a compatibilidade falhar, rejeitar a proposta e exibir uma mensagem de domínio acionável."
payload:
  # project omitted: DecisionsSearch derives it from the current workspace folder
  repo: "example-project"
  pr_number: 41
  title: "feat: validação de PileType nas propostas"
  summary: "O objetivo do PR é impedir propostas com estaca incompatível com a carga admissível. A mudança adiciona a validação no serviço de propostas, propaga o erro para o formulário e cobre o comportamento com teste; quando a condição é detectada, a criação é bloqueada e o usuário recebe uma explicação operacional."
  changed_files:
    - services/proposal_service.py
    - models/pile_type.py
    - frontend/src/components/ProposalForm.tsx
    - spec/services/proposal_service_spec.rb
  areas: [propostas, estacas]
  pr_url: "https://github.com/example-org/example-project/pull/41"
  work_item_url: "https://trello.com/c/example-project-pile-validation"
  work_item_summary: "Impedir propostas com PileType incompatível com a carga admissível"
  event_date: "2026-06-28T14:30:00Z"
  authors: ["example-org"]
  branch: "feat/pile-type-validation"
  status: merged
```

## Verification

- [ ] `memory.pr.query(project, repo, pr_number)` retorna o PR recém-criado
- [ ] `changed_files` coincide com `gh pr diff --name-only`/Git, sem truncamento
- [ ] `summary` e objetivo são prosa operacional e não apenas o título
- [ ] `pr_url` e `work_item_url` estão preenchidos, ou a exceção foi aprovada explicitamente
- [ ] Nenhuma razão foi fabricada a partir de nomes de arquivo

## Anti-patterns

- Do NOT criar memória só do título ou de um recap humano — leia PR, diff e histórico.
- Do NOT reduzir `changed_files` aos arquivos "importantes" — o payload leva a lista completa.
- Do NOT inventar objetivo, stakeholders, regras, action triggers ou `work_item_url`.
- Do NOT usar `git blame` para substituir o PR/diff nem para responder autoria de linha nesta skill.
- Do NOT transformar uma ocorrência isolada em `CodePattern`, `BusinessRule` ou `ArchitecturalDecision`.

## Failure modes & recovery

- **MCP DecisionsSearch indisponível** → STOP, informe o usuário com instrução de setup. Nunca "persista depois".
- **`gh` não autenticado ou PR indisponível** → STOP e instrua `gh auth login`; nunca prosseguir de memória.
- **Git checkout não contém o arquivo/commit** → informar a lacuna e pedir checkout/ref correto; não inventar a cadeia.
- **PR sem card/ticket linkado** → perguntar `work_item_url` e `work_item_summary`; se não existir card, usar `work_item_url: "none"` somente com aprovação explícita.
- **Objetivo ou motivação não evidenciados** → persistir somente após marcar a lacuna no preview e obter confirmação explícita; nunca preencher com suposição.

## RECAP

- PRMemory é Git Blame operacional: PR + diff + histórico, todos os arquivos e razão em prosa.
- FeatureDescription exige narrativa, trigger, stakeholders, arquivos, regras e action triggers; ela é derivada dentro do PRMemory, não um nó inventado.
- Nunca persista sem preview e confirmação; nunca invente fatos ou reduza a lista de arquivos.
