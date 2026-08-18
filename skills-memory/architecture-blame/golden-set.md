# Golden-set: architecture-blame

Rode cada prompt 3-5x. Medir: (1) roteou pra skill certa? (2) procedure na ordem? (3) output no schema?
Meta: ≥80% dos canônicos passam nas 3 métricas; 0 anti-canônicos ativam.

| # | Tipo | Prompt | Resultado esperado |
|---|------|--------|--------------------|
| 1 | Canônico | "por que usamos Qdrant?" | ativa esta skill |
| 2 | Canônico | "por que a arquitetura é monolito?" | ativa esta skill |
| 3 | Canônico | "qual a decisão vigente sobre cache e o que ela substituiu?" | ativa esta skill |
| 4 | Canônico | "que alternativas foram descartadas pra busca híbrida?" | ativa esta skill |
| 5 | Canônico | "architecture blame do módulo de embeddings" | ativa esta skill |
| 6 | Anti-canônico | "que decisões arquiteturais temos?" | roteia pra `query-memory` |
| 7 | Anti-canônico | "registra a decisão de usar Redis" | roteia pra `create-architectural-decision-memory` |
| 8 | Anti-canônico | "por que esse service é estruturado assim?" | roteia pra `code-blame` |
| 9 | Ambíguo | "por que escolhemos isso?" | pergunta ao usuário (AD ou reasoning de task?), não chuta |
| 10 | Ambíguo | "explica a arquitetura" | pergunta ao usuário (doc rápido ou timeline?), não chuta |
