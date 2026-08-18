# Golden-set: decisionssearch-capture

Rode cada prompt 3-5x. Medir: (1) roteou pra skill certa? (2) procedure na ordem? (3) output no schema?
Meta: ≥80% dos canônicos passam nas 3 métricas; 0 anti-canônicos ativam.

| # | Tipo | Prompt | Resultado esperado |
|---|------|--------|--------------------|
| 1 | Canônico | "fecha o PR capturando as memórias" | ativa esta skill |
| 2 | Canônico | "decisionssearch capture" | ativa esta skill |
| 3 | Canônico | "popula a memória com esse PR" | ativa esta skill |
| 4 | Canônico | "roda a captura de fim de PR" | ativa esta skill |
| 5 | Canônico | "acabei o PR 52, captura tudo" | ativa esta skill |
| 6 | Anti-canônico | "cria só a memória do PR" | roteia pra `create-pr-memory` |
| 7 | Anti-canônico | "registra essa regra de negócio" | roteia pra `create-business-rule-memory` |
| 8 | Anti-canônico | "atualiza os docs do decisionssearch" | roteia pra `decisionssearch-update` |
| 9 | Ambíguo | "salva tudo" | pergunta ao usuário (captura ou update?), não chuta |
| 10 | Ambíguo | "terminei" | pergunta ao usuário (capturar memórias?), não chuta |
