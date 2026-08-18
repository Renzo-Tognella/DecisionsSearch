---
name: <verb-first-kebab-case, ≤30 chars>
description: "<1ª frase = o que a skill faz + quando ativa — é a ÚNICA coisa que o router lê>. Use quando o usuário disser '<frase literal 1>', '<frase literal 2>' ou <contexto observável>. Do NOT use for <caso vizinho> — use `<outra-skill>`."
version: 1.0.0
metadata:
  decisionssearch:
    memory_class: <PRMemory|BusinessRule|ArchitecturalDecision|CodePattern|Reasoning|none>
    feature_description: <"narrativa derivada dentro de PRMemory"|none>
    context_file: <.decisionssearch/business.md|.decisionssearch/architecture.md|.decisionssearch/code-patterns.md|none>
    related_skills: [<name>, ...]
---

# <Skill Name>

<Persona em 1-2 frases: quem está executando e qual o objetivo observável.>

**CORE RULE:** <A regra inegociável desta skill em 1-2 frases. Ex.: "Nunca persista sem preview e confirmação do usuário.">

## Contrato de evidência e prosa

- PRMemory operacional deve usar PR/diff/Git como fonte primária, preservar todos os changed_files e escrever objetivo e summary em prosa.
- Quando aplicável, FeatureDescription é uma narrativa derivada dentro de PRMemory com narrative, trigger, stakeholders, files, rules e action_triggers; não é um nó ou campo Python adicional.
- BusinessRule e ArchitecturalDecision devem sobreviver à troca da implementação e ser escritos em prosa; PRs e arquivos entram como evidência/link.
- CodePattern exige evidência explícita de reutilização ou padronização; uma ocorrência isolada permanece em PRMemory.
- Se a skill persistir ou criar links, preview e confirmação explícita continuam obrigatórios.

## When to activate

- Trigger phrases: "<frase exata 1>", "<frase exata 2>"
- Contexts: <estados de projeto/sessão que disparam>

**Do NOT activate for:**
- <caso 1> → use `<skill-vizinha>`
- <caso 2> → apenas responda conversacionalmente

## Inputs

- `<param>` (required): <tipo + 1 linha>. Fonte: <sessão|usuário|digest|arquivo>.
- `<param>` (optional, default: `<valor>`): <...>

## Context load

- Carregar `<.decisionssearch/arquivo.md>` (se `metadata.decisionssearch.context_file` ≠ none).
- Se o arquivo não existir → sugerir `decisionssearch-init` e STOP.
- Verificar MCP DecisionsSearch com um `memory.query` trivial antes de qualquer escrita.

## Procedure

1. **<Nome do passo>** — <ação com tool exata>.
   - Reason: <o que observar no resultado>.
   - Decision: if <condição> → <branch>; else → continue.
2. **<...>** — <...>
3. **Self-Refine gate** — rascunhe a memória/saída completa e critique contra:
   - Todos os campos obrigatórios preenchidos (sem string vazia)?
   - Linguagem estável, livre de implementação transitória?
   - `modules`/`domain` pertencem à taxonomia do `.decisionssearch/business.md`?
   - Duplicata buscada no grafo (`memory.query`)?
   Refine o rascunho até as 4 respostas serem "sim"; só então mostre o preview.
4. **Preview + confirmação** — mostre o payload completo; persista apenas com "sim" explícito.

## Output Schema

```yaml
<campo>: <tipo | enum>
<campo>: <tipo>
```

### Example

```yaml
# Exemplo PREENCHIDO com dados reais (nunca schema abstrato — anti-pattern A5)
<campo>: "<valor real>"
```

## Verification

- [ ] `<comando/check executável>` (ex.: `memory.get(<id>)` retorna o nó criado)
- [ ] Output bate com o schema (todos os campos, tipos certos)
- [ ] Nenhum anti-pattern abaixo foi disparado

## Anti-patterns

- Do NOT <comportamento proibido 1 — concreto>.
- Do NOT <comportamento proibido 2>.
- Do NOT <comportamento proibido 3>.

## Failure modes & recovery

- **MCP DecisionsSearch indisponível** → STOP, informe o usuário com instrução de setup. Nunca "persista depois".
- **<erro específico da skill>** → <recovery>.

## RECAP

- <CORE RULE repetida>
- <2ª regra crítica>
- <3ª regra crítica>
