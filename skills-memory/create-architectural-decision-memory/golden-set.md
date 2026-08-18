# Golden-set: create-architectural-decision-memory

Rode cada prompt 3-5x. Medir: (1) roteou pra skill certa? (2) procedure na ordem? (3) output no schema?
Meta: ≥80% dos canônicos passam nas 3 métricas; 0 anti-canônicos ativam.

| # | Tipo | Prompt | Resultado esperado |
|---|------|--------|--------------------|
| 1 | Canônico | "registra a decisão de usar Qdrant" | ativa esta skill |
| 2 | Canônico | "documenta por que escolhemos monolito" | ativa esta skill |
| 3 | Canônico | "cria a AD do cache em memória" | ativa esta skill |
| 4 | Canônico | "salva essa decisão com as alternativas que descartamos" | ativa esta skill |
| 5 | Canônico | "captura a decisão arquitetural desse PR" | ativa esta skill |
| 6 | Anti-canônico | "por que a arquitetura é assim?" | roteia pra `architecture-blame` |
| 7 | Anti-canônico | "salva o plano que seguimos nessa task" | roteia pra `capture-reasoning` |
| 8 | Anti-canônico | "regra: proposta exige aprovação do engenheiro" | roteia pra `create-business-rule-memory` |
| 9 | Ambíguo | "guarda o que decidimos hoje" | pergunta ao usuário (AD ou reasoning?), não chuta |
| 10 | Ambíguo | "documenta a escolha" | pergunta ao usuário (durável ou de percurso?), não chuta |
