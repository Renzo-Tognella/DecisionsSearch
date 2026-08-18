# Golden-set: code-blame

Rode cada prompt 3-5x. Medir: (1) roteou pra skill certa? (2) procedure na ordem? (3) output no schema?
Meta: ≥80% dos canônicos passam nas 3 métricas; 0 anti-canônicos ativam.

| # | Tipo | Prompt | Resultado esperado |
|---|------|--------|--------------------|
| 1 | Canônico | "por que esse arquivo é assim?" | ativa esta skill |
| 2 | Canônico | "que PRs mexeram no services/proposal_service.py?" | ativa esta skill |
| 3 | Canônico | "qual a razão dessa validação aqui?" | ativa esta skill |
| 4 | Canônico | "code blame desse módulo" | ativa esta skill |
| 5 | Canônico | "de onde veio essa lógica?" | ativa esta skill |
| 6 | Anti-canônico | "quem commitou essa linha?" | não ativa (usa `git blame` direto) |
| 7 | Anti-canônico | "como a regra evoluiu?" | roteia pra `rule-blame` |
| 8 | Anti-canônico | "por que usamos essa lib?" | roteia pra `architecture-blame` |
| 9 | Ambíguo | "explica esse código" | pergunta ao usuário (blame ou leitura?), não chuta |
| 10 | Ambíguo | "isso tá certo?" | pergunta ao usuário (review, não blame), não chuta |
