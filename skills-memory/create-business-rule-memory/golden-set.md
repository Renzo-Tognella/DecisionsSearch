# Golden-set: create-business-rule-memory

Rode cada prompt 3-5x. Medir: (1) roteou pra skill certa? (2) procedure na ordem? (3) output no schema?
Meta: ≥80% dos canônicos passam nas 3 métricas; 0 anti-canônicos ativam.

| # | Tipo | Prompt | Resultado esperado |
|---|------|--------|--------------------|
| 1 | Canônico | "cria a regra de negócio de que toda proposta precisa de carga admissível" | ativa esta skill |
| 2 | Canônico | "registra essa regra do PileType" | ativa esta skill |
| 3 | Canônico | "salva como regra: cliente só vê propostas aprovadas" | ativa esta skill |
| 4 | Canônico | "essa validação é uma regra de negócio, guarda ela" | ativa esta skill |
| 5 | Canônico | "captura as regras de negócio desse PR" | ativa esta skill |
| 6 | Anti-canônico | "por que essa regra é assim?" | roteia pra `rule-blame` |
| 7 | Anti-canônico | "decidimos usar Qdrant, registra" | roteia pra `create-architectural-decision-memory` |
| 8 | Anti-canônico | "padroniza os nomes de service" | roteia pra `create-code-pattern-memory` |
| 9 | Ambíguo | "guarda essa decisão" | pergunta ao usuário (regra ou AD?), não chuta |
| 10 | Ambíguo | "isso é importante, salva" | pergunta ao usuário (classe?), não chuta |
