#!/usr/bin/env bash
# audit.sh <skill-dir> — valida uma skill contra o template canônico. Exit 0 = PASS.
set -u
DIR="${1:?uso: audit.sh <skill-dir>}"
F="$DIR/SKILL.md"
G="$DIR/golden-set.md"
fail=0
err() { echo "FAIL: $1"; fail=1; }

[ -f "$F" ] || { echo "FAIL: $F não existe"; exit 1; }

# Frontmatter é contrato (P1)
head -1 "$F" | grep -q '^---$' || err "sem frontmatter"
grep -q '^name: [a-z][a-z0-9-]*$' "$F" || err "name ausente ou não-kebab"
NAME=$(grep '^name:' "$F" | head -1 | awk '{print $2}')
# ≤40 (PDF sugere ≤30; suíte usa nomes compostos como create-architectural-decision-memory)
[ ${#NAME} -le 40 ] || err "name > 40 chars"
[ "$(basename "$DIR")" = "$NAME" ] || err "diretório != name do frontmatter"
grep -q '^description:' "$F" || err "description ausente"
grep '^description:' "$F" | grep -q 'Do NOT use' || err "description sem 'Do NOT use' (A2)"
grep '^description:' "$F" | grep -q "'" || err "description sem trigger literal em aspas (A1)"
grep -q '^version: [0-9]' "$F" || err "version ausente (A14)"

# Primazia: CORE RULE nas primeiras 30 linhas
head -30 "$F" | grep -q 'CORE RULE' || err "CORE RULE fora do topo (primazia)"

# Seções obrigatórias
while IFS= read -r s; do
  grep -qF "$s" "$F" || err "seção ausente: $s"
done <<'SECTIONS'
## When to activate
## Inputs
## Procedure
## Output Schema
### Example
## Verification
## Anti-patterns
## Failure modes & recovery
## RECAP
SECTIONS
grep -qF 'Do NOT activate for' "$F" || err "sem 'Do NOT activate for' no corpo (P3)"
grep -qF 'Self-Refine' "$F" || err "sem Self-Refine gate no Procedure"

# Recência: RECAP é a última seção
[ "$(grep '^## ' "$F" | tail -1)" = "## RECAP" ] || err "RECAP não é a última seção (recência)"

# Anti-patterns ≥3 (A7)
AP=$(sed -n '/^## Anti-patterns/,/^## /p' "$F" | grep -c '^- ')
[ "$AP" -ge 3 ] || err "menos de 3 anti-patterns ($AP)"

# Progressive disclosure (A9)
LINES=$(wc -l < "$F")
[ "$LINES" -le 500 ] || err "SKILL.md com $LINES linhas (>500) — mover pra references/"

# Golden-set (P10)
[ -f "$G" ] || err "golden-set.md ausente"
if [ -f "$G" ]; then
  for t in "Canônico" "Anti-canônico" "Ambíguo"; do
    grep -q "$t" "$G" || err "golden-set sem prompts do tipo $t"
  done
fi

[ $fail -eq 0 ] && echo "PASS: $NAME"
exit $fail
