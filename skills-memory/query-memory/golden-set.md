# Golden-set: query-memory

Rode cada prompt 3-5x. Medir: (1) roteou pra skill certa? (2) procedure na ordem? (3) output no schema?
Meta: ≥80% dos canônicos passam nas 3 métricas; 0 anti-canônicos ativam.

| # | Tipo | Prompt | Resultado esperado |
|---|------|--------|--------------------|
| 1 | Canônico | "já fizemos algo assim antes?" | ativa esta skill |
| 2 | Canônico | "o que mudou no módulo de propostas?" | ativa esta skill |
| 3 | Canônico | "tem alguma regra sobre carga admissível?" | ativa esta skill |
| 4 | Canônico | "busca na memória sobre reranking" | ativa esta skill |
| 5 | Canônico | "que decisões temos sobre banco de dados?" | ativa esta skill |
| 6 | Anti-canônico | "como essa regra evoluiu até aqui?" | roteia pra `rule-blame` |
| 7 | Anti-canônico | "por que esse arquivo é assim?" | roteia pra `code-blame` |
| 8 | Anti-canônico | "por que usamos Qdrant?" | roteia pra `architecture-blame` |
| 9 | Ambíguo | "me conta sobre o projeto" | pergunta ao usuário (grafo ou docs .decisionssearch?), não chuta |
| 10 | Ambíguo | "o que temos aí?" | pergunta ao usuário (escopo?), não chuta |
