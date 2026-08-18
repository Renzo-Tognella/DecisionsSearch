from __future__ import annotations

import logging
import os

from decisionssearch.infrastructure.config.env_utils import env_int
from decisionssearch.application.memory.extraction_service import (
    get_llm_api_key,
    get_llm_base_url,
    get_llm_chat_model,
    get_llm_provider,
)
from decisionssearch.infrastructure.ai.providers.model_provider import get_openrouter_headers

logger = logging.getLogger(__name__)


class HyDEService:
    HYPOTHETICAL_PROMPT = (
        "Given the question below, write a detailed technical answer "
        "as if you are documenting a design decision or rule. "
        "Use technical language.\n\n"
        "Question: {query}\n\n"
        "Answer:"
    )

    def __init__(self):
        self.model = os.getenv("HYDE_MODEL", "") or get_llm_chat_model()
        self.min_query_length = env_int("HYDE_MIN_QUERY_LENGTH", 15)
        self.provider = get_llm_provider()
        self.client = self._build_client()

    def _build_client(self):
        api_key = get_llm_api_key()
        if not api_key:
            return None
        try:
            from openai import AsyncOpenAI

            base_url = get_llm_base_url()
            if self.provider == "gemini":
                base_url = os.getenv(
                    "GEMINI_BASE_URL",
                    "https://generativelanguage.googleapis.com/v1beta/openai",
                )
            kwargs = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            headers = get_openrouter_headers(self.provider)
            if headers:
                kwargs["default_headers"] = headers
            return AsyncOpenAI(**kwargs)
        except Exception as error:
            logger.warning("Failed to build HyDE client: %s", error)
            return None

    def should_expand(self, query: str, force: bool = False) -> bool:
        # HyDE é opt-in pelo caller (force=True). O gate por comprimento ficou
        # como fallback: queries reais quase nunca têm < 15 chars, então sem o
        # opt-in o HyDE virava código morto (ver Q6 no plano de melhorias).
        if force:
            return True
        return len(query.strip()) < self.min_query_length

    async def expand(self, query: str, force: bool = False) -> str:
        if not self.should_expand(query, force=force):
            return query
        if not self.client:
            return query
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You generate detailed technical "
                            "documentation from brief queries."
                        ),
                    },
                    {
                        "role": "user",
                        "content": self.HYPOTHETICAL_PROMPT.format(query=query),
                    },
                ],
                max_tokens=200,
                temperature=0.3,
            )
            expanded = response.choices[0].message.content.strip()
            if expanded:
                return f"{query} {expanded}"
            return query
        except Exception as error:
            logger.warning("HyDE expansion failed: %s", error)
            return query
