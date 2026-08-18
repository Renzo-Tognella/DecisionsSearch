# Golden-set: create-code-pattern-memory

Rode cada prompt 3-5x. Medir: (1) roteou pra skill certa? (2) procedure na ordem? (3) output no schema?
Meta: ≥80% dos canônicos passam nas 3 métricas; 0 anti-canônicos ativam.

| # | Tipo | Prompt | Resultado esperado |
|---|------|--------|--------------------|
| 1 | Canônico | "registra o padrão de repository que usamos" | ativa esta skill |
| 2 | Canônico | "documenta essa convenção de naming" | ativa esta skill |
| 3 | Canônico | "salva esse padrão de fixture de teste" | ativa esta skill |
| 4 | Canônico | "isso virou padrão, captura" | ativa esta skill |
| 5 | Canônico | "guarda a estrutura de pastas como padrão" | ativa esta skill |
| 6 | Anti-canônico | "por que esse arquivo é assim?" | roteia pra `code-blame` |
| 7 | Anti-canônico | "decidimos usar SQLAlchemy, registra" | roteia pra `create-architectural-decision-memory` |
| 8 | Anti-canônico | "atualiza o code-patterns.md" | roteia pra `decisionssearch-update` |
| 9 | Ambíguo | "padroniza isso" | pergunta ao usuário (capturar ou aplicar?), não chuta |
| 10 | Ambíguo | "salva como referência" | pergunta ao usuário (classe?), não chuta |
