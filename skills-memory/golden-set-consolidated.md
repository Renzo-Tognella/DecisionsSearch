# Golden-set consolidado — DecisionsSearch Skills Suite v2

Agrega os 130 prompts (13 skills × 10) dos `golden-set.md` individuais numa bateria única. Objetivo: testar **roteamento cruzado** — algo que um golden-set por skill não pega, porque cada um é avaliado com a skill isolada. Aqui as 13 skills estão instaladas ao mesmo tempo (como estarão em `.claude/skills/` de um projeto real), e o que importa é se a `description` de cada uma continua vencendo o router certo quando as outras 12 também estão competindo.

**Pré-requisito para rodar:** as 13 skills instaladas num projeto (via `decisionssearch-init`) e o MCP DecisionsSearch conectado. Sem isso, este arquivo é só o roteiro — não executável nesta sessão (ver nota no fim).

**Como rodar:** para cada linha, envie o prompt numa sessão limpa (sem contexto prévio de qual skill usar) e registre: (a) qual skill ativou, (b) bateu com o "Esperado"? Meta: 100% das colisões da Seção 1 corretas — são o teste mais informativo da suíte inteira.

---

## Seção 1 — Colisões conhecidas (rodar primeiro)

Prompts que aparecem em mais de um golden-set individual — canônico numa skill, anti-canônico ou ambíguo em outra(s). Se o router erra aqui, a `description` de alguma das skills envolvidas está genérica demais ou faltando "Do NOT use for".

### Cluster A — "por que esse arquivo é assim?"

| Prompt | Aparece em (papel) | Esperado |
|---|---|---|
| "por que esse arquivo é assim?" | code-blame (canônico); create-pr-memory (anti); create-code-pattern-memory (anti); query-memory (anti) | `code-blame` |
| "que PRs mexeram no services/proposal_service.py?" | code-blame (canônico) | `code-blame` |
| "por que o código valida assim?" | rule-blame (anti) | `code-blame` |
| "por que esse service é estruturado assim?" | architecture-blame (anti) | `code-blame` |

### Cluster B — "registra a decisão de usar X" (tecnologia)

| Prompt | Aparece em (papel) | Esperado |
|---|---|---|
| "registra a decisão de usar Qdrant" | create-architectural-decision-memory (canônico); capture-reasoning (anti) | `create-architectural-decision-memory` |
| "decidimos usar Qdrant, registra" | create-business-rule-memory (anti) | `create-architectural-decision-memory` |
| "decidimos usar SQLAlchemy, registra" | create-code-pattern-memory (anti) | `create-architectural-decision-memory` |
| "registra a decisão de usar Redis" | architecture-blame (anti) | `create-architectural-decision-memory` |
| "por que usamos Qdrant?" | architecture-blame (canônico); query-memory (anti) | `architecture-blame` |

### Cluster C — "captura/salva as memórias desse PR" (genérico vs. orquestrado)

| Prompt | Aparece em (papel) | Esperado |
|---|---|---|
| "captura as memórias desse PR" | decisionssearch-init (anti) | `decisionssearch-capture` |
| "captura as regras de negócio desse PR" | create-business-rule-memory (canônico) | `create-business-rule-memory` (escopo já restrito a regra) |
| "captura a decisão arquitetural desse PR" | create-architectural-decision-memory (canônico) | `create-architectural-decision-memory` |
| "cria só a memória do PR" | decisionssearch-capture (anti) | `create-pr-memory` |
| "cria a memória do PR" | capture-reasoning (anti); link-pr-to-memory (anti) | `create-pr-memory` |
| "fecha o PR capturando as memórias" | decisionssearch-capture (canônico) | `decisionssearch-capture` |

Teste-chave do Cluster C: só a versão **sem qualificador de classe** ("captura as memórias desse PR") deve ir para a orquestradora; com qualificador ("as regras", "a decisão") deve ir direto pra skill específica.

### Cluster D — evolução/histórico ("por que X é assim" temporal)

| Prompt | Aparece em (papel) | Esperado |
|---|---|---|
| "como a regra de aprovação de propostas chegou nesse estado?" | rule-blame (canônico) | `rule-blame` |
| "como essa regra evoluiu até aqui?" | query-memory (anti); code-blame (anti) | `rule-blame` |
| "por que a arquitetura é assim?" | create-architectural-decision-memory (anti) | `architecture-blame` |
| "por que a arquitetura é monolito?" | architecture-blame (canônico) | `architecture-blame` |
| "que decisões arquiteturais temos?" | architecture-blame (anti) | `query-memory` |

### Cluster E — reasoning vs. AD vs. busca

| Prompt | Aparece em (papel) | Esperado |
|---|---|---|
| "captura o reasoning dessa task" | capture-reasoning (canônico) | `capture-reasoning` |
| "salva o plano que seguimos nessa task" | create-architectural-decision-memory (anti) | `capture-reasoning` |
| "já fizemos algo assim antes?" | query-memory (canônico); capture-reasoning (anti) | `query-memory` |
| "documenta por que escolhemos monolito" | create-architectural-decision-memory (canônico) | `create-architectural-decision-memory` (decisão durável, não processo) |

### Cluster F — "salva/guarda isso" genérico (a zona cinza real)

Nenhum destes tem qualificador de classe — são o teste de maior risco de falso-positivo da suíte:

| Prompt | Skill de origem (papel: ambíguo) |
|---|---|
| "guarda isso que fizemos" | create-pr-memory |
| "salva o trabalho de hoje" | create-pr-memory |
| "guarda o que decidimos hoje" | create-architectural-decision-memory |
| "salva o que aprendemos" | capture-reasoning |
| "isso é importante, salva" | create-business-rule-memory |
| "salva como referência" | create-code-pattern-memory |
| "salva tudo" | decisionssearch-capture |
| "terminei" | decisionssearch-capture |
| "associa isso" | link-pr-to-memory |
| "atualiza a memória" | decisionssearch-update |

Esperado para todo o Cluster F: **nenhuma skill ativa direto** — o agente pergunta qual classe/ação antes de agir. Se qualquer uma ativar sem perguntar, é regressão (a skill "roubou" um prompt genérico demais).

### Cluster G — atualizar documento vs. atualizar grafo

| Prompt | Aparece em (papel) | Esperado |
|---|---|---|
| "atualiza o business.md com as memórias novas" | decisionssearch-init (anti) | `decisionssearch-update` |
| "atualiza o code-patterns.md" | create-code-pattern-memory (anti) | `decisionssearch-update` |
| "atualiza o architecture.md com as decisões novas" | decisionssearch-update (canônico) | `decisionssearch-update` |
| "configura o decisionssearch nesse projeto" | decisionssearch-update (anti) | `decisionssearch-init` |

---

## Seção 2 — Inventário completo por skill (varredura sistemática)

Os 130 prompts originais, para rodar a bateria inteira depois da Seção 1. Ordem e conteúdo idênticos aos `golden-set.md` de cada skill — reproduzidos aqui só para conveniência de execução em lote.

| # | Skill | Tipo | Prompt | Esperado |
|---|---|---|---|---|
| 1 | decisionssearch-init | Canônico | "decisionssearch init" | decisionssearch-init |
| 2 | decisionssearch-init | Canônico | "configura o decisionssearch aqui" | decisionssearch-init |
| 3 | decisionssearch-init | Canônico | "instala as skills de memória nesse projeto" | decisionssearch-init |
| 4 | decisionssearch-init | Canônico | "quero começar a usar o decisionssearch no ExampleProject" | decisionssearch-init |
| 5 | decisionssearch-init | Canônico | "setup do decisionssearch" | decisionssearch-init |
| 6 | decisionssearch-init | Anti | "atualiza o business.md com as memórias novas" | decisionssearch-update |
| 7 | decisionssearch-init | Anti | "captura as memórias desse PR" | decisionssearch-capture |
| 8 | decisionssearch-init | Anti | "o que é o decisionssearch?" | nenhuma (conversa) |
| 9 | decisionssearch-init | Ambíguo | "arruma o decisionssearch" | pergunta |
| 10 | decisionssearch-init | Ambíguo | "prepara esse projeto" | pergunta |
| 11 | create-pr-memory | Canônico | "cria a memória do PR 41" | create-pr-memory |
| 12 | create-pr-memory | Canônico | "salva esse PR no decisionssearch" | create-pr-memory |
| 13 | create-pr-memory | Canônico | "registra o PR que acabamos de mergear" | create-pr-memory |
| 14 | create-pr-memory | Canônico | URL de PR + "guarda isso na memória" | create-pr-memory |
| 15 | create-pr-memory | Canônico | "documenta o PR #12 na memória" | create-pr-memory |
| 16 | create-pr-memory | Anti | "que PRs mexeram nesse arquivo?" | code-blame |
| 17 | create-pr-memory | Anti | "cria a regra de negócio desse PR" | create-business-rule-memory |
| 18 | create-pr-memory | Anti | "faz merge do PR 41" | nenhuma |
| 19 | create-pr-memory | Ambíguo | "guarda isso que fizemos" | pergunta |
| 20 | create-pr-memory | Ambíguo | "salva o trabalho de hoje" | pergunta |
| 21 | create-business-rule-memory | Canônico | "cria a regra de negócio de que toda proposta precisa de carga admissível" | create-business-rule-memory |
| 22 | create-business-rule-memory | Canônico | "registra essa regra do PileType" | create-business-rule-memory |
| 23 | create-business-rule-memory | Canônico | "salva como regra: cliente só vê propostas aprovadas" | create-business-rule-memory |
| 24 | create-business-rule-memory | Canônico | "essa validação é uma regra de negócio, guarda ela" | create-business-rule-memory |
| 25 | create-business-rule-memory | Canônico | "captura as regras de negócio desse PR" | create-business-rule-memory |
| 26 | create-business-rule-memory | Anti | "por que essa regra é assim?" | rule-blame |
| 27 | create-business-rule-memory | Anti | "decidimos usar Qdrant, registra" | create-architectural-decision-memory |
| 28 | create-business-rule-memory | Anti | "padroniza os nomes de service" | create-code-pattern-memory |
| 29 | create-business-rule-memory | Ambíguo | "guarda essa decisão" | pergunta |
| 30 | create-business-rule-memory | Ambíguo | "isso é importante, salva" | pergunta |
| 31 | create-architectural-decision-memory | Canônico | "registra a decisão de usar Qdrant" | create-architectural-decision-memory |
| 32 | create-architectural-decision-memory | Canônico | "documenta por que escolhemos monolito" | create-architectural-decision-memory |
| 33 | create-architectural-decision-memory | Canônico | "cria a AD do cache em memória" | create-architectural-decision-memory |
| 34 | create-architectural-decision-memory | Canônico | "salva essa decisão com as alternativas que descartamos" | create-architectural-decision-memory |
| 35 | create-architectural-decision-memory | Canônico | "captura a decisão arquitetural desse PR" | create-architectural-decision-memory |
| 36 | create-architectural-decision-memory | Anti | "por que a arquitetura é assim?" | architecture-blame |
| 37 | create-architectural-decision-memory | Anti | "salva o plano que seguimos nessa task" | capture-reasoning |
| 38 | create-architectural-decision-memory | Anti | "regra: proposta exige aprovação do engenheiro" | create-business-rule-memory |
| 39 | create-architectural-decision-memory | Ambíguo | "guarda o que decidimos hoje" | pergunta |
| 40 | create-architectural-decision-memory | Ambíguo | "documenta a escolha" | pergunta |
| 41 | create-code-pattern-memory | Canônico | "registra o padrão de repository que usamos" | create-code-pattern-memory |
| 42 | create-code-pattern-memory | Canônico | "documenta essa convenção de naming" | create-code-pattern-memory |
| 43 | create-code-pattern-memory | Canônico | "salva esse padrão de fixture de teste" | create-code-pattern-memory |
| 44 | create-code-pattern-memory | Canônico | "isso virou padrão, captura" | create-code-pattern-memory |
| 45 | create-code-pattern-memory | Canônico | "guarda a estrutura de pastas como padrão" | create-code-pattern-memory |
| 46 | create-code-pattern-memory | Anti | "por que esse arquivo é assim?" | code-blame |
| 47 | create-code-pattern-memory | Anti | "decidimos usar SQLAlchemy, registra" | create-architectural-decision-memory |
| 48 | create-code-pattern-memory | Anti | "atualiza o code-patterns.md" | decisionssearch-update |
| 49 | create-code-pattern-memory | Ambíguo | "padroniza isso" | pergunta |
| 50 | create-code-pattern-memory | Ambíguo | "salva como referência" | pergunta |
| 51 | capture-reasoning | Canônico | "captura o reasoning dessa task" | capture-reasoning |
| 52 | capture-reasoning | Canônico | "salva o plano e o porquê das escolhas" | capture-reasoning |
| 53 | capture-reasoning | Canônico | "registra como resolvemos esse card" | capture-reasoning |
| 54 | capture-reasoning | Canônico | "guarda o raciocínio dessa sessão" | capture-reasoning |
| 55 | capture-reasoning | Canônico | "fecha o card salvando o processo" | capture-reasoning |
| 56 | capture-reasoning | Anti | "registra a decisão de usar Qdrant" | create-architectural-decision-memory |
| 57 | capture-reasoning | Anti | "já fizemos algo assim antes?" | query-memory |
| 58 | capture-reasoning | Anti | "cria a memória do PR" | create-pr-memory |
| 59 | capture-reasoning | Ambíguo | "salva o que aprendemos" | pergunta |
| 60 | capture-reasoning | Ambíguo | "documenta a sessão" | pergunta |
| 61 | link-pr-to-memory | Canônico | "linka o PR 41 à regra do PileType" | link-pr-to-memory |
| 62 | link-pr-to-memory | Canônico | "conecta essa memória ao PR" | link-pr-to-memory |
| 63 | link-pr-to-memory | Canônico | "cria o link IMPLEMENTS entre PR e decisão" | link-pr-to-memory |
| 64 | link-pr-to-memory | Canônico | "relaciona essas duas regras" | link-pr-to-memory |
| 65 | link-pr-to-memory | Canônico | "linka tudo que criamos agora ao PR" | link-pr-to-memory |
| 66 | link-pr-to-memory | Anti | "cria a memória do PR" | create-pr-memory |
| 67 | link-pr-to-memory | Anti | "que memórias esse PR tem linkadas?" | query-memory |
| 68 | link-pr-to-memory | Anti | "por que esse arquivo mudou?" | code-blame |
| 69 | link-pr-to-memory | Ambíguo | "associa isso" | pergunta |
| 70 | link-pr-to-memory | Ambíguo | "amarra as pontas" | pergunta |
| 71 | decisionssearch-capture | Canônico | "fecha o PR capturando as memórias" | decisionssearch-capture |
| 72 | decisionssearch-capture | Canônico | "decisionssearch capture" | decisionssearch-capture |
| 73 | decisionssearch-capture | Canônico | "popula a memória com esse PR" | decisionssearch-capture |
| 74 | decisionssearch-capture | Canônico | "roda a captura de fim de PR" | decisionssearch-capture |
| 75 | decisionssearch-capture | Canônico | "acabei o PR 52, captura tudo" | decisionssearch-capture |
| 76 | decisionssearch-capture | Anti | "cria só a memória do PR" | create-pr-memory |
| 77 | decisionssearch-capture | Anti | "registra essa regra de negócio" | create-business-rule-memory |
| 78 | decisionssearch-capture | Anti | "atualiza os docs do decisionssearch" | decisionssearch-update |
| 79 | decisionssearch-capture | Ambíguo | "salva tudo" | pergunta |
| 80 | decisionssearch-capture | Ambíguo | "terminei" | pergunta |
| 81 | query-memory | Canônico | "já fizemos algo assim antes?" | query-memory |
| 82 | query-memory | Canônico | "o que mudou no módulo de propostas?" | query-memory |
| 83 | query-memory | Canônico | "tem alguma regra sobre carga admissível?" | query-memory |
| 84 | query-memory | Canônico | "busca na memória sobre reranking" | query-memory |
| 85 | query-memory | Canônico | "que decisões temos sobre banco de dados?" | query-memory |
| 86 | query-memory | Anti | "como essa regra evoluiu até aqui?" | rule-blame |
| 87 | query-memory | Anti | "por que esse arquivo é assim?" | code-blame |
| 88 | query-memory | Anti | "por que usamos Qdrant?" | architecture-blame |
| 89 | query-memory | Ambíguo | "me conta sobre o projeto" | pergunta |
| 90 | query-memory | Ambíguo | "o que temos aí?" | pergunta |
| 91 | rule-blame | Canônico | "como a regra de aprovação de propostas chegou nesse estado?" | rule-blame |
| 92 | rule-blame | Canônico | "histórico da regra do PileType" | rule-blame |
| 93 | rule-blame | Canônico | "que PRs mudaram essa regra?" | rule-blame |
| 94 | rule-blame | Canônico | "quando essa regra mudou e por quê?" | rule-blame |
| 95 | rule-blame | Canônico | "rule blame da regra de carga admissível" | rule-blame |
| 96 | rule-blame | Anti | "tem regra sobre desconto?" | query-memory |
| 97 | rule-blame | Anti | "cria essa regra de negócio" | create-business-rule-memory |
| 98 | rule-blame | Anti | "por que o código valida assim?" | code-blame |
| 99 | rule-blame | Ambíguo | "por que isso é assim?" | pergunta |
| 100 | rule-blame | Ambíguo | "quem mudou isso?" | pergunta |
| 101 | architecture-blame | Canônico | "por que usamos Qdrant?" | architecture-blame |
| 102 | architecture-blame | Canônico | "por que a arquitetura é monolito?" | architecture-blame |
| 103 | architecture-blame | Canônico | "qual a decisão vigente sobre cache e o que ela substituiu?" | architecture-blame |
| 104 | architecture-blame | Canônico | "que alternativas foram descartadas pra busca híbrida?" | architecture-blame |
| 105 | architecture-blame | Canônico | "architecture blame do módulo de embeddings" | architecture-blame |
| 106 | architecture-blame | Anti | "que decisões arquiteturais temos?" | query-memory |
| 107 | architecture-blame | Anti | "registra a decisão de usar Redis" | create-architectural-decision-memory |
| 108 | architecture-blame | Anti | "por que esse service é estruturado assim?" | code-blame |
| 109 | architecture-blame | Ambíguo | "por que escolhemos isso?" | pergunta |
| 110 | architecture-blame | Ambíguo | "explica a arquitetura" | pergunta |
| 111 | code-blame | Canônico | "por que esse arquivo é assim?" | code-blame |
| 112 | code-blame | Canônico | "que PRs mexeram no services/proposal_service.py?" | code-blame |
| 113 | code-blame | Canônico | "qual a razão dessa validação aqui?" | code-blame |
| 114 | code-blame | Canônico | "code blame desse módulo" | code-blame |
| 115 | code-blame | Canônico | "de onde veio essa lógica?" | code-blame |
| 116 | code-blame | Anti | "quem commitou essa linha?" | nenhuma (git blame) |
| 117 | code-blame | Anti | "como a regra evoluiu?" | rule-blame |
| 118 | code-blame | Anti | "por que usamos essa lib?" | architecture-blame |
| 119 | code-blame | Ambíguo | "explica esse código" | pergunta |
| 120 | code-blame | Ambíguo | "isso tá certo?" | pergunta |
| 121 | decisionssearch-update | Canônico | "decisionssearch update" | decisionssearch-update |
| 122 | decisionssearch-update | Canônico | "sincroniza os docs com a memória" | decisionssearch-update |
| 123 | decisionssearch-update | Canônico | "atualiza o architecture.md com as decisões novas" | decisionssearch-update |
| 124 | decisionssearch-update | Canônico | "puxa as regras novas pro business.md" | decisionssearch-update |
| 125 | decisionssearch-update | Canônico | "roda o update do decisionssearch" | decisionssearch-update |
| 126 | decisionssearch-update | Anti | "captura as memórias do PR" | decisionssearch-capture |
| 127 | decisionssearch-update | Anti | "configura o decisionssearch nesse projeto" | decisionssearch-init |
| 128 | decisionssearch-update | Anti | "busca na memória sobre propostas" | query-memory |
| 129 | decisionssearch-update | Ambíguo | "atualiza a memória" | pergunta |
| 130 | decisionssearch-update | Ambíguo | "deixa tudo em dia" | pergunta |

---

## Métricas de aceite

- **Seção 1 (colisões):** 100% esperado — qualquer erro aqui é sinal de `description` a corrigir antes de considerar a suíte pronta.
- **Seção 2 (varredura completa):** ≥80% dos canônicos corretos, 0% dos anti-canônicos ativando a skill errada (podem falhar "ativar a vizinha certa" sem quebrar o critério de não ativar a própria).
- Toda falha vira 1 edição no `SKILL.md` da skill envolvida (1 seção por iteração, conforme o loop fechado do `_template/README`) — não mexer em 2 skills na mesma iteração, pra isolar causa.

## Nota de execução

Este arquivo não é executável nesta sessão: rodar a bateria requer as 13 skills instaladas num projeto real (via `decisionssearch-init`) e observação de qual skill o router de fato ativa por prompt — isso depende do host (Claude Code) carregando as skills instaladas, não de uma tool disponível aqui. Use este arquivo como roteiro na primeira rodada real de `decisionssearch-init` (Task 17 do plano de implementação).
