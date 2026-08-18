# Golden-set: decisionssearch-update

Rode cada prompt 3-5x. Medir: (1) roteou pra skill certa? (2) procedure na ordem? (3) output no schema?
Meta: ≥80% dos canônicos passam nas 3 métricas; 0 anti-canônicos ativam.

| # | Tipo | Prompt | Resultado esperado |
|---|------|--------|--------------------|
| 1 | Canônico | "decisionssearch update" | ativa esta skill |
| 2 | Canônico | "sincroniza os docs com a memória" | ativa esta skill |
| 3 | Canônico | "atualiza o architecture.md com as decisões novas" | ativa esta skill |
| 4 | Canônico | "puxa as regras novas pro business.md" | ativa esta skill |
| 5 | Canônico | "roda o update do decisionssearch" | ativa esta skill |
| 6 | Anti-canônico | "captura as memórias do PR" | roteia pra `decisionssearch-capture` |
| 7 | Anti-canônico | "configura o decisionssearch nesse projeto" | roteia pra `decisionssearch-init` |
| 8 | Anti-canônico | "busca na memória sobre propostas" | roteia pra `query-memory` |
| 9 | Ambíguo | "atualiza a memória" | pergunta ao usuário (grafo ou docs?), não chuta |
| 10 | Ambíguo | "deixa tudo em dia" | pergunta ao usuário (update ou capture?), não chuta |
