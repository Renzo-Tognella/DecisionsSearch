# Golden-set: create-pr-memory

Rode cada prompt 3-5x. Medir: (1) roteou pra skill certa? (2) procedure na ordem? (3) output no schema?
Meta: ≥80% dos canônicos passam nas 3 métricas; 0 anti-canônicos ativam.

| # | Tipo | Prompt | Resultado esperado |
|---|------|--------|--------------------|
| 1 | Canônico | "cria a memória do PR 41" | ativa esta skill |
| 2 | Canônico | "salva esse PR no decisionssearch" | ativa esta skill |
| 3 | Canônico | "registra o PR que acabamos de mergear" | ativa esta skill |
| 4 | Canônico | "https://github.com/org/repo/pull/12 — guarda isso na memória" | ativa esta skill |
| 5 | Canônico | "documenta o PR #12 na memória" | ativa esta skill |
| 6 | Anti-canônico | "que PRs mexeram nesse arquivo?" | roteia pra `code-blame` |
| 7 | Anti-canônico | "cria a regra de negócio desse PR" | roteia pra `create-business-rule-memory` |
| 8 | Anti-canônico | "faz merge do PR 41" | não ativa skill nenhuma |
| 9 | Ambíguo | "guarda isso que fizemos" | pergunta ao usuário (PR ou reasoning?), não chuta |
| 10 | Ambíguo | "salva o trabalho de hoje" | pergunta ao usuário (escopo?), não chuta |
