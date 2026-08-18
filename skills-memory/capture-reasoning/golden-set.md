# Golden-set: capture-reasoning

Rode cada prompt 3-5x. Medir: (1) roteou pra skill certa? (2) procedure na ordem? (3) output no schema?
Meta: ≥80% dos canônicos passam nas 3 métricas; 0 anti-canônicos ativam.

| # | Tipo | Prompt | Resultado esperado |
|---|------|--------|--------------------|
| 1 | Canônico | "captura o reasoning dessa task" | ativa esta skill |
| 2 | Canônico | "salva o plano e o porquê das escolhas" | ativa esta skill |
| 3 | Canônico | "registra como resolvemos esse card" | ativa esta skill |
| 4 | Canônico | "guarda o raciocínio dessa sessão" | ativa esta skill |
| 5 | Canônico | "fecha o card salvando o processo" | ativa esta skill |
| 6 | Anti-canônico | "registra a decisão de usar Qdrant" | roteia pra `create-architectural-decision-memory` |
| 7 | Anti-canônico | "já fizemos algo assim antes?" | roteia pra `query-memory` |
| 8 | Anti-canônico | "cria a memória do PR" | roteia pra `create-pr-memory` |
| 9 | Ambíguo | "salva o que aprendemos" | pergunta ao usuário (reasoning ou pattern?), não chuta |
| 10 | Ambíguo | "documenta a sessão" | pergunta ao usuário (escopo?), não chuta |
