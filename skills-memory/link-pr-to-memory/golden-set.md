# Golden-set: link-pr-to-memory

Rode cada prompt 3-5x. Medir: (1) roteou pra skill certa? (2) procedure na ordem? (3) output no schema?
Meta: ≥80% dos canônicos passam nas 3 métricas; 0 anti-canônicos ativam.

| # | Tipo | Prompt | Resultado esperado |
|---|------|--------|--------------------|
| 1 | Canônico | "linka o PR 41 à regra do PileType" | ativa esta skill |
| 2 | Canônico | "conecta essa memória ao PR" | ativa esta skill |
| 3 | Canônico | "cria o link IMPLEMENTS entre PR e decisão" | ativa esta skill |
| 4 | Canônico | "relaciona essas duas regras" | ativa esta skill |
| 5 | Canônico | "linka tudo que criamos agora ao PR" | ativa esta skill |
| 6 | Anti-canônico | "cria a memória do PR" | roteia pra `create-pr-memory` |
| 7 | Anti-canônico | "que memórias esse PR tem linkadas?" | roteia pra `query-memory` |
| 8 | Anti-canônico | "por que esse arquivo mudou?" | roteia pra `code-blame` |
| 9 | Ambíguo | "associa isso" | pergunta ao usuário (o quê a quê?), não chuta |
| 10 | Ambíguo | "amarra as pontas" | pergunta ao usuário (links ou update?), não chuta |
