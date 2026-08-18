# Golden-set: decisionssearch-init

Rode cada prompt 3-5x. Medir: (1) roteou pra skill certa? (2) procedure na ordem? (3) output no schema?
Meta: ≥80% dos canônicos passam nas 3 métricas; 0 anti-canônicos ativam.

| # | Tipo | Prompt | Resultado esperado |
|---|------|--------|--------------------|
| 1 | Canônico | "decisionssearch init" | ativa esta skill |
| 2 | Canônico | "configura o decisionssearch aqui" | ativa esta skill |
| 3 | Canônico | "instala as skills de memória nesse projeto" | ativa esta skill |
| 4 | Canônico | "quero começar a usar o decisionssearch no ExampleProject" | ativa esta skill |
| 5 | Canônico | "setup do decisionssearch" | ativa esta skill |
| 6 | Anti-canônico | "atualiza o business.md com as memórias novas" | roteia pra `decisionssearch-update` |
| 7 | Anti-canônico | "captura as memórias desse PR" | roteia pra `decisionssearch-capture` |
| 8 | Anti-canônico | "o que é o decisionssearch?" | não ativa skill nenhuma (conversa) |
| 9 | Ambíguo | "arruma o decisionssearch" | pergunta ao usuário (init ou update?), não chuta |
| 10 | Ambíguo | "prepara esse projeto" | pergunta ao usuário (escopo?), não chuta |
