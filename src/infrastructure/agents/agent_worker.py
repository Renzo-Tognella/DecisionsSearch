from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from decisionssearch.infrastructure.ai.providers.model_provider import get_openrouter_headers

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    success: bool
    output: str = ""
    error: str = ""
    returncode: int = -1
    extracted: dict = field(default_factory=dict)


@runtime_checkable
class AgentWorker(Protocol):
    async def run(self, prompt: str, env: dict | None = None) -> AgentResult: ...


def _extract_json(output: str) -> dict:
    match = re.search(r"```json\s*(\{.*?\})\s*```", output, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    for match in re.finditer(r"\{[^{}]*\}", output):
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
    return {}


class OpenCodeWorker:
    def __init__(self, workdir: str = ".", agent: str = "bug-fixer", timeout: int = 600):
        self.workdir = Path(workdir)
        self.agent = agent
        self.timeout = timeout

    async def run(self, prompt: str, env: dict | None = None) -> AgentResult:
        import asyncio

        env_vars = {**os.environ, **(env or {})}
        env_vars.setdefault("OPENCODE_NO_COLOR", "1")
        cmd = ["opencode", "--agent", self.agent, "run", prompt]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workdir), env=env_vars,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
            output = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")
            result = AgentResult(
                success=(proc.returncode == 0),
                output=output, error=err,
                returncode=proc.returncode or -1,
            )
            result.extracted = _extract_json(output)
            return result
        except asyncio.TimeoutError:
            return AgentResult(success=False, error=f"Timeout after {self.timeout}s", returncode=124)


class CodexWorker:
    SYSTEM_PROMPT = """You are an expert bug-fixing agent. Analyze the error and produce a fix.
Always respond with a JSON block containing:
{"status": "fixed"|"needs_human"|"unclear", "root_cause": "...", "fix_description": "...", "files_modified": ["..."], "confidence": 0.0-1.0, "risks": ["..."], "testing_notes": "..."}"""

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str = "",
        auth_type: str = "api_key",
        timeout: int = 600,
        base_url: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
        provider_label: str = "OpenAI",
        default_headers: dict[str, str] | None = None,
    ):
        self.model = model
        self.auth_type = auth_type
        self.timeout = timeout
        self.base_url = base_url or "https://api.openai.com/v1"
        self.api_key_env = api_key_env
        self.provider_label = provider_label
        self.default_headers = default_headers or {}

        if auth_type == "api_key":
            self.api_key = api_key or os.environ.get(self.api_key_env, "")
        else:
            self.api_key = api_key

    async def run(self, prompt: str, env: dict | None = None) -> AgentResult:
        if not self.api_key:
            return AgentResult(
                success=False,
                error=(
                    f"{self.api_key_env} not set — add it to decisionssearch.yaml "
                    "or env var"
                ),
            )

        try:
            import httpx
        except ImportError:
            return AgentResult(success=False, error="httpx not installed")

        url = self.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        headers.update(self.default_headers)
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                result = AgentResult(success=True, output=text, returncode=0)
                result.extracted = _extract_json(text)
                return result
        except httpx.TimeoutException:
            return AgentResult(success=False, error=f"Timeout after {self.timeout}s", returncode=124)
        except httpx.HTTPStatusError as e:
            return AgentResult(
                success=False,
                error=f"{self.provider_label} API {e.response.status_code}: {e.response.text[:500]}",
            )
        except Exception as e:
            return AgentResult(success=False, error=f"{self.provider_label} API error: {e}")


class OpenRouterWorker(CodexWorker):
    """Worker de investigação usando o endpoint OpenAI-compatible do OpenRouter."""

    def __init__(
        self,
        model: str = "openai/gpt-4o-mini",
        api_key: str = "",
        timeout: int = 600,
        base_url: str | None = None,
    ):
        super().__init__(
            model=model,
            api_key=api_key,
            timeout=timeout,
            base_url=base_url or "https://openrouter.ai/api/v1",
            api_key_env="OPENROUTER_API_KEY",
            provider_label="OpenRouter",
            default_headers=get_openrouter_headers("openrouter"),
        )


class ClaudeWorker:
    SYSTEM_PROMPT = """You are an expert bug-fixing agent. Analyze the error and produce a fix.
Always respond with a JSON block containing:
{"status": "fixed"|"needs_human"|"unclear", "root_cause": "...", "fix_description": "...", "files_modified": ["..."], "confidence": 0.0-1.0, "risks": ["..."], "testing_notes": "..."}"""

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key: str = "",
        auth_type: str = "api_key",
        session_key: str = "",
        timeout: int = 600,
        base_url: str | None = None,
    ):
        self.model = model
        self.auth_type = auth_type
        self.timeout = timeout

        if auth_type == "session":
            self.session_key = session_key or os.environ.get("CLAUDE_SESSION_KEY", "")
            self.api_key = ""
            self.base_url = "https://claude.ai"
        else:
            self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
            self.session_key = ""
            self.base_url = base_url or "https://api.anthropic.com"

    async def run(self, prompt: str, env: dict | None = None) -> AgentResult:
        if self.auth_type == "session":
            return await self._run_session(prompt)
        return await self._run_api(prompt)

    async def _run_api(self, prompt: str) -> AgentResult:
        if not self.api_key:
            return AgentResult(
                success=False,
                error="ANTHROPIC_API_KEY not set — add it to decisionssearch.yaml (agent.claude.api_key) or env var",
            )

        try:
            import httpx
        except ImportError:
            return AgentResult(success=False, error="httpx not installed")

        url = self.base_url.rstrip("/") + "/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "system": self.SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}],
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                text = "".join(
                    b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
                )
                result = AgentResult(success=True, output=text, returncode=0)
                result.extracted = _extract_json(text)
                return result
        except httpx.TimeoutException:
            return AgentResult(success=False, error=f"Timeout after {self.timeout}s", returncode=124)
        except httpx.HTTPStatusError as e:
            return AgentResult(
                success=False, error=f"Anthropic API {e.response.status_code}: {e.response.text[:500]}"
            )
        except Exception as e:
            return AgentResult(success=False, error=f"Anthropic API error: {e}")

    async def _run_session(self, prompt: str) -> AgentResult:
        if not self.session_key:
            return AgentResult(
                success=False,
                error="CLAUDE_SESSION_KEY not set — get it from claude.ai (DevTools > Cookies > sessionKey)",
            )

        try:
            import httpx
        except ImportError:
            return AgentResult(success=False, error="httpx not installed")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                org_resp = await client.get(
                    "https://claude.ai/api/organizations",
                    headers={"Cookie": f"sessionKey={self.session_key}"},
                )
                org_resp.raise_for_status()
                orgs = org_resp.json()
                if not orgs:
                    return AgentResult(success=False, error="No Claude organizations found — check session key")
                org_id = orgs[0].get("uuid", "")

                url = f"https://claude.ai/api/organizations/{org_id}/chat_conversations"
                headers = {
                    "Cookie": f"sessionKey={self.session_key}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                }
                payload = {
                    "prompt": prompt,
                    "timezone": "UTC",
                    "model": self.model,
                    "system_prompt": self.SYSTEM_PROMPT,
                }
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()

                text = self._parse_sse_response(resp.text)
                result = AgentResult(success=True, output=text, returncode=0)
                result.extracted = _extract_json(text)
                return result
        except httpx.TimeoutException:
            return AgentResult(success=False, error=f"Timeout after {self.timeout}s", returncode=124)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return AgentResult(
                    success=False,
                    error="Claude session key expired — get a new one from claude.ai (DevTools > Cookies > sessionKey)",
                )
            return AgentResult(
                success=False, error=f"Claude session {e.response.status_code}: {e.response.text[:500]}"
            )
        except Exception as e:
            return AgentResult(success=False, error=f"Claude session error: {e}")

    @staticmethod
    def _parse_sse_response(raw: str) -> str:
        chunks = []
        for line in raw.split("\n"):
            if line.startswith("data: "):
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                    completion = event.get("completion", "")
                    if completion:
                        chunks.append(completion)
                except json.JSONDecodeError:
                    continue
        return "".join(chunks)


class ZaiWorker:
    SYSTEM_PROMPT = """You are an expert bug-fixing agent. Analyze the error and produce a fix.
Always respond with a JSON block containing:
{"status": "fixed"|"needs_human"|"unclear", "root_cause": "...", "fix_description": "...", "files_modified": ["..."], "confidence": 0.0-1.0, "risks": ["..."], "testing_notes": "..."}"""

    def __init__(
        self,
        model: str = "glm-4-plus",
        api_key: str = "",
        timeout: int = 600,
        base_url: str | None = None,
    ):
        self.model = model
        self.timeout = timeout
        self.api_key = api_key or os.environ.get("ZAI_API_KEY", "")
        self.base_url = base_url or "https://open.bigmodel.cn/api/paas/v4"

    async def run(self, prompt: str, env: dict | None = None) -> AgentResult:
        if not self.api_key:
            return AgentResult(
                success=False,
                error="ZAI_API_KEY not set — add it to decisionssearch.yaml (agent.zai.api_key) or env var",
            )

        try:
            import httpx
        except ImportError:
            return AgentResult(success=False, error="httpx not installed")

        url = self.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                result = AgentResult(success=True, output=text, returncode=0)
                result.extracted = _extract_json(text)
                return result
        except httpx.TimeoutException:
            return AgentResult(success=False, error=f"Timeout after {self.timeout}s", returncode=124)
        except httpx.HTTPStatusError as e:
            return AgentResult(success=False, error=f"Z.ai API {e.response.status_code}: {e.response.text[:500]}")
        except Exception as e:
            return AgentResult(success=False, error=f"Z.ai API error: {e}")


def create_agent_worker(config: dict[str, Any]) -> AgentWorker:
    provider = config.get("provider", "opencode")
    timeout = config.get("timeout", 600)
    workdir = config.get("workdir", ".")

    if provider == "opencode":
        oc = config.get("opencode", {})
        return OpenCodeWorker(
            workdir=workdir,
            agent=oc.get("agent", "bug-fixer"),
            timeout=timeout,
        )
    elif provider == "codex":
        cx = config.get("codex", {})
        return CodexWorker(
            model=cx.get("model", "gpt-4o"),
            api_key=cx.get("api_key", ""),
            auth_type=cx.get("auth_type", "api_key"),
            timeout=timeout,
            base_url=cx.get("base_url"),
        )
    elif provider == "claude":
        cl = config.get("claude", {})
        return ClaudeWorker(
            model=cl.get("model", "claude-sonnet-4-20250514"),
            api_key=cl.get("api_key", ""),
            auth_type=cl.get("auth_type", "api_key"),
            session_key=cl.get("session_key", ""),
            timeout=timeout,
            base_url=cl.get("base_url"),
        )
    elif provider == "zai":
        zai = config.get("zai", {})
        return ZaiWorker(
            model=zai.get("model", "glm-4-plus"),
            api_key=zai.get("api_key", ""),
            timeout=timeout,
            base_url=zai.get("base_url"),
        )
    elif provider == "openrouter":
        openrouter = config.get("openrouter", {})
        return OpenRouterWorker(
            model=openrouter.get("model", "openai/gpt-4o-mini"),
            api_key=openrouter.get("api_key", ""),
            timeout=timeout,
            base_url=openrouter.get("base_url"),
        )
    else:
        raise ValueError(
            f"Unknown agent provider: {provider!r}. "
            "Use 'opencode', 'codex', 'claude', 'zai', or 'openrouter'."
        )
