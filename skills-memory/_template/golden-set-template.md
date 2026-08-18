# Golden-set: <skill-name>

Rode cada prompt 3-5x. Medir: (1) roteou pra skill certa? (2) procedure na ordem? (3) output no schema?
Meta: ≥80% dos canônicos passam nas 3 métricas; 0 anti-canônicos ativam.

| # | Tipo | Prompt | Resultado esperado |
|---|------|--------|--------------------|
| 1 | Canônico | "<prompt>" | ativa esta skill |
| 2 | Canônico | "<prompt>" | ativa esta skill |
| 3 | Canônico | "<prompt>" | ativa esta skill |
| 4 | Canônico | "<prompt>" | ativa esta skill |
| 5 | Canônico | "<prompt>" | ativa esta skill |
| 6 | Anti-canônico | "<prompt>" | roteia pra `<skill-vizinha>` |
| 7 | Anti-canônico | "<prompt>" | roteia pra `<skill-vizinha>` |
| 8 | Anti-canônico | "<prompt>" | não ativa skill nenhuma |
| 9 | Ambíguo | "<prompt>" | pergunta ao usuário, não chuta |
| 10 | Ambíguo | "<prompt>" | pergunta ao usuário, não chuta |
