from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from decisionssearch.domain.memory.memory_candidate import EvidenceRef, MemoryCandidate
from decisionssearch.application.memory.memory_awareness import build_memory_awareness_instruction
from decisionssearch.infrastructure.ai.providers.model_provider import (
    PROVIDER_CONFIGS,
    get_embedding_dimensions,
    get_embedding_model,
    get_llm_api_key,
    get_llm_base_url,
    get_llm_chat_model,
    get_llm_provider,
    get_openrouter_headers,
)

logger = logging.getLogger(__name__)

__all__ = [
    "PROVIDER_CONFIGS",
    "get_embedding_dimensions",
    "get_embedding_model",
    "get_llm_api_key",
    "get_llm_base_url",
    "get_llm_chat_model",
    "get_llm_provider",
    "ExtractionResult",
    "ExtractionService",
]


class ExtractionResult(BaseModel):
    decision: Literal["memory_candidates", "no_memory"] = "no_memory"
    reason: str = ""
    candidates: list[MemoryCandidate] = Field(default_factory=list)


class ExtractionService:
    def __init__(self, sanitization=None):
        self.sanitization = sanitization
        self.model = get_llm_chat_model()
        self.provider = get_llm_provider()
        self.client = self._build_openai_client()
        self._structured_client = self._build_structured_client()

    def _build_openai_client(self):
        api_key = get_llm_api_key()
        if not api_key:
            return None
        try:
            from openai import AsyncOpenAI

            base_url = get_llm_base_url()
            kwargs = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            headers = get_openrouter_headers(self.provider)
            if headers:
                kwargs["default_headers"] = headers
            return AsyncOpenAI(**kwargs)
        except Exception as error:
            logger.warning("Failed to build OpenAI-compatible client: %s", error)
            return None

    def _build_structured_client(self):
        if not self.client:
            return None
        try:
            import instructor
            # OpenRouter rejects the OpenAI tool-call transport for this
            # account's data-policy configuration, while its JSON response
            # transport is supported. Keep the provider-specific choice here
            # so other OpenAI-compatible providers retain the default mode.
            if self.provider == "openrouter":
                return instructor.from_openai(self.client, mode=instructor.Mode.JSON)
            return instructor.from_openai(self.client)
        except Exception as error:
            logger.warning("Failed to build structured extraction client: %s", error)
            return None

    async def extract_candidates(
        self,
        content: str,
        project: str = "CORE",
        probable_category: str | None = None,
        domain: list[str] | None = None,
        *,
        allow_heuristic_fallback: bool = False,
        evidence: list[EvidenceRef] | None = None,
        source_event_id: str = "",
        context_instruction: str = "",
    ) -> list[MemoryCandidate]:
        normalized = content.strip()
        if not normalized:
            return []
        if self.sanitization:
            normalized = self.sanitization.sanitize(normalized)

        if self._structured_client:
            try:
                result = await self._structured_client.chat.completions.create(
                    model=self.model,
                    response_model=ExtractionResult,
                    messages=[
                        {
                            "role": "system",
                            "content": self._system_prompt(
                                project,
                                probable_category,
                                context_instruction=context_instruction,
                            ),
                        },
                        {"role": "user", "content": normalized},
                    ],
                    max_retries=2,
                )
                if result.decision == "no_memory":
                    return []
                return self._attach_source_metadata(
                    result.candidates,
                    evidence=evidence,
                    source_event_id=source_event_id,
                )
            except Exception as error:
                logging.getLogger(__name__).warning(
                    "Structured extraction failed, using heuristic fallback: %s", error
                )

        if not allow_heuristic_fallback:
            logger.info("Extração estruturada indisponível; nenhum candidato foi forçado")
            return []

        category = probable_category or self._infer_category(normalized)
        summary = self._prose_sentence(normalized[:420])
        title = self._prose_sentence(summary.splitlines()[0][:120]) or "Memory candidate"

        candidate = MemoryCandidate(
            project=project,
            type=category,
            domain=domain or [],
            title=title,
            summary=summary,
            details=self._prose_sentence(normalized[:1500]),
            objective=self._prose_sentence(normalized[:320]),
            evidence=[
                EvidenceRef(
                    type="conversation",
                    ref="mcp_ingest",
                    snippet=summary[:160],
                )
            ],
        )
        return self._attach_source_metadata(
            [candidate], evidence=evidence, source_event_id=source_event_id
        )

    def _infer_category(self, text: str) -> str:
        text_lower = text.lower()
        if any(token in text_lower for token in ("decision", "decisão", "adr")):
            return "ArchitecturalDecision"
        if any(token in text_lower for token in ("regra", "rule", "obrigatório", "deve")):
            return "BusinessRule"
        if any(token in text_lower for token in ("convenção", "naming", "style", "guard clause")):
            return "DesignRule"
        if any(token in text_lower for token in ("feature", "fluxo", "flow", "trigger", "gatilho")):
            return "FeatureDescription"
        return "DesignPattern"

    def _system_prompt(
        self,
        project: str,
        category: str | None,
        *,
        context_instruction: str = "",
    ) -> str:
        category_hint = f"Categoria provável: {category}." if category else ""
        return f"""Você está extraindo memória durável para o projeto {project}.
{category_hint}

{build_memory_awareness_instruction(context_instruction)}

As memórias devem ser escritas em prosa narrativa, usando a linguagem predominante da evidência.
Mantenha a mesma voz e o mesmo tempo verbal ao longo do candidato. Cada title, summary, details,
objective, trigger e architectural_rationale deve ser uma frase completa e legível; não escreva
fragmentos, rótulos com dois-pontos, listas em linha ou instruções de prompt. Os campos que são
listas devem conter itens curtos apenas quando forem nomes de arquivos, pessoas, atores ou regras.

<category_contracts>
- FeatureDescription: narra como uma feature ou fluxo funciona, por que existe e como começa,
  incluindo objective, trigger, stakeholders, action_triggers, related_files e business_rules.
- BusinessRule: registra uma condição ou restrição observável do domínio, com contexto suficiente
  para alguém explicar quando ela se aplica. Não transforme uma mera alteração de código em regra.
- ArchitecturalDecision: registra uma escolha estrutural ou tecnológica durável, sua motivação,
  constraints, trade-offs e pelo menos uma alternativa rejeitada por motivo factual. O resumo curto
  deve ser pesquisável por uma pergunta natural; details deve explicar a decisão em prosa.
- DesignRule: registra uma convenção durável de apresentação ou interação, não um detalhe acidental.
- DesignPattern: registra uma solução visual ou de interação reutilizável e comprovada.
- CodePattern: registra somente um padrão de implementação reutilizável, observável em mais de um
</category_contracts>

<evidence_gates>
Não classifique uma mudança como ArchitecturalDecision apenas porque ela menciona API, banco,
dependência, migração, camada ou refatoração. É necessário encontrar uma escolha, uma razão e uma
alternativa/trade-off que possam ser citados na fonte. Não classifique uma mudança como CodePattern
apenas porque o código parece elegante ou porque um arquivo contém uma classe conhecida. É necessário
encontrar uma declaração de padrão/convenção, uma regra de replicação ou o mesmo idiom em pelo menos
dois locais independentes, com examples concretos. Um único diff pode gerar FeatureDescription e
BusinessRule sem gerar AD/CodePattern. Isso é esperado.
</evidence_gates>

Regras de admissão:
1. Cada candidato deve conter ao menos uma evidência concreta e rastreável.
2. Não invente stakeholders, regras, gatilhos, objetivos, alternativas ou relações não sustentadas.
3. Um PR pode gerar zero candidatos duráveis. Retorne lista vazia quando só houver uma mudança local,
   correção mecânica ou informação insuficiente.
4. Não copie URLs, números de PR ou listas de arquivos para summary. A proveniência fica na evidência
   e os arquivos relacionados ficam em related_files; use o resumo para a busca semântica.
5. proposed_weight deve ficar entre 0 e 1 e confidence deve refletir a força da evidência.
6. Escreva uma FeatureDescription quando a evidência descrever um fluxo ou comportamento de ponta a ponta;
   não force uma regra de negócio, decisão ou padrão de código para preencher uma categoria.
7. Antes de responder, faça uma triagem independente por categoria. Se somente a narrativa da alteração
   estiver sustentada, retorne apenas FeatureDescription; se nenhuma memória durável estiver sustentada,
   retorne no_memory.

Exemplos de decisão:
- Uma mudança isolada em um arquivo: FeatureDescription ou no_memory; nunca CodePattern por inferência.
- Um PR dizendo que duas abordagens foram comparadas e que uma foi escolhida por compatibilidade: ArchitecturalDecision.
- O mesmo idiom de implementação aparecendo em dois módulos e sendo declarado como convenção: CodePattern.

Formato de saída: {{"decision": "memory_candidates" | "no_memory", "reason": "...",
"candidates": [...]}}. Quando não houver memória, use decision="no_memory" e candidates=[].
"""

    @staticmethod
    def _attach_source_metadata(
        candidates: list[MemoryCandidate],
        *,
        evidence: list[EvidenceRef] | None,
        source_event_id: str,
    ) -> list[MemoryCandidate]:
        """Anexa evidência conhecida pelo pipeline sem substituir a saída do LLM."""

        if not evidence and not source_event_id:
            return candidates

        enriched: list[MemoryCandidate] = []
        for candidate in candidates:
            known = list(candidate.evidence)
            existing = {(item.type, item.ref) for item in known}
            for item in evidence or []:
                if (item.type, item.ref) not in existing:
                    known.append(item)
                    existing.add((item.type, item.ref))
            enriched.append(
                candidate.model_copy(
                    update={
                        "evidence": known,
                        "source_event_id": source_event_id or candidate.source_event_id,
                    }
                )
            )
        return enriched

    @staticmethod
    def _prose_sentence(value: str) -> str:
        """Normaliza o fallback local sem transformar evidência em prosa truncada."""

        text = " ".join(str(value or "").split()).strip()
        if not text:
            return ""
        if text[-1] not in ".!?":
            text += "."
        return text
