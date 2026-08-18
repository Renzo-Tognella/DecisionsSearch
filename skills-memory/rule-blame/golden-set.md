# Golden-set: rule-blame

Rode cada prompt 3-5x. Medir: (1) roteou pra skill certa? (2) procedure na ordem? (3) output no schema?
Meta: ≥80% dos canônicos passam nas 3 métricas; 0 anti-canônicos ativam.

| # | Tipo | Prompt | Resultado esperado |
|---|------|--------|--------------------|
| 1 | Canônico | "como a regra de aprovação de propostas chegou nesse estado?" | ativa esta skill |
| 2 | Canônico | "histórico da regra do PileType" | ativa esta skill |
| 3 | Canônico | "que PRs mudaram essa regra?" | ativa esta skill |
| 4 | Canônico | "quando essa regra mudou e por quê?" | ativa esta skill |
| 5 | Canônico | "rule blame da regra de carga admissível" | ativa esta skill |
| 6 | Anti-canônico | "tem regra sobre desconto?" | roteia pra `query-memory` |
| 7 | Anti-canônico | "cria essa regra de negócio" | roteia pra `create-business-rule-memory` |
| 8 | Anti-canônico | "por que o código valida assim?" | roteia pra `code-blame` |
| 9 | Ambíguo | "por que isso é assim?" | pergunta ao usuário (regra, código ou arquitetura?), não chuta |
| 10 | Ambíguo | "quem mudou isso?" | pergunta ao usuário (git blame ou grafo?), não chuta |
