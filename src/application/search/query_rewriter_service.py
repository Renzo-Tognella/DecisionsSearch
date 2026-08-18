"""Reescrita de consultas em prosa antes da busca híbrida."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from decisionssearch.infrastructure.ai.providers.model_provider import (
    get_llm_api_key,
    get_llm_base_url,
    get_llm_chat_model,
    get_llm_provider,
    get_openrouter_headers,
)

logger = logging.getLogger(__name__)


class RewrittenQuery(BaseModel):
    rewritten_query: str = Field(min_length=1)
    intent: str = ""
    entities: list[str] = Field(default_factory=list)


class QueryRewriterService:
    """Converte consultas fragmentadas em perguntas narrativas pesquisáveis."""

    SYSTEM_PROMPT = """Você reescreve consultas para a memória de engenharia de software.
Escreva uma única pergunta em prosa, com sujeito, ação e objeto claros, preservando
nomes de arquivos, módulos, PRs, erros, estados e termos técnicos fornecidos pelo usuário.
Não responda à pergunta, não invente contexto, não transforme a consulta em lista e não
remova pistas que possam ser usadas em uma busca híbrida. Se a pergunta mencionar um
arquivo, mantenha o arquivo. Se perguntar por uma causa, mantenha o objetivo de encontrar
PRs concorrentes, resumo da mudança, regra de negócio, decisão arquitetural ou narrativa
de feature. A saída deve permanecer na linguagem da consulta original.
"""

    def __init__(self, client=None):
        self.model = get_llm_chat_model()
        self.provider = get_llm_provider()
        self.client = client if client is not None else self._build_client()
        self._structured_client = self._build_structured_client()

    def _build_client(self):
        api_key = get_llm_api_key()
        if not api_key:
            return None
        try:
            from openai import AsyncOpenAI

            kwargs = {"api_key": api_key}
            base_url = get_llm_base_url()
            if base_url:
                kwargs["base_url"] = base_url
            headers = get_openrouter_headers(self.provider)
            if headers:
                kwargs["default_headers"] = headers
            return AsyncOpenAI(**kwargs)
        except Exception as error:  # pragma: no cover - depends on optional SDK
            logger.warning("Falha ao criar cliente do query rewriter: %s", error)
            return None

    def _build_structured_client(self):
        if not self.client:
            return None
        try:
            import instructor

            if self.provider == "openrouter":
                return instructor.from_openai(self.client, mode=instructor.Mode.JSON)
            return instructor.from_openai(self.client)
        except Exception as error:  # pragma: no cover - optional integration
            logger.warning("Falha ao criar cliente estruturado do query rewriter: %s", error)
            return None

    async def rewrite(
        self,
        query: str,
        *,
        project: str = "",
        category: str | None = None,
    ) -> str:
        normalized = self._normalize(query)
        if not normalized or not self._structured_client:
            return normalized

        context = f"Projeto: {project}." if project else ""
        if category:
            context += f" Categoria provável: {category}."
        try:
            result = await self._structured_client.chat.completions.create(
                model=self.model,
                response_model=RewrittenQuery,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"{context}\nConsulta original: {normalized}",
                    },
                ],
                max_retries=2,
            )
            rewritten = self._normalize(result.rewritten_query)
            return rewritten or normalized
        except Exception as error:  # pragma: no cover - provider-dependent
            logger.warning("Falha na reescrita de consulta; usando texto original: %s", error)
            return normalized

    @staticmethod
    def _normalize(query: str) -> str:
        text = " ".join(str(query or "").split()).strip()
        return text
