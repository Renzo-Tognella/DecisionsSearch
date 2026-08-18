from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_ENV_VAR_RE = re.compile(r"\$\{(\w+)(?::([^}]*))?\}")


def _resolve_env(value: Any) -> Any:
    if isinstance(value, str):
        def repl(m):
            return os.environ.get(m.group(1), m.group(2) or "")
        return _ENV_VAR_RE.sub(repl, value)
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(v) for v in value]
    return value


def _deep_merge(base: dict, override: dict) -> dict:
    result = {**base}
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


_DEFAULTS: dict[str, Any] = {
    "mode": "light",
    "data_dir": "data",
    "agent": {
        "provider": "opencode",
        "workdir": ".",
        "timeout": 600,
        "opencode": {"agent": "bug-fixer"},
        "codex": {"model": "gpt-4o", "api_key": ""},
        "claude": {"model": "claude-sonnet-4-20250514", "api_key": ""},
        "zai": {"model": "glm-4-plus", "api_key": ""},
        "openrouter": {"model": "openai/gpt-4o-mini", "api_key": ""},
    },
    "notifications": {
        "slack": {"enabled": False, "webhook_url": ""},
        "generic_webhook": {"enabled": False, "url": "", "headers": {}},
    },
    "scheduler": {
        "persistence": "memory",
        "sqlite_path": "data/scheduler.db",
        "jobs": {
            "daily_consolidation": "0 3 * * *",
            "daily_summary": "0 4 * * *",
        },
    },
    "safety": {
        "min_confidence": 0.7,
        "max_auto_fixes_per_hour": 3,
        "blocked_paths": ["auth/", "security/", ".env", "credentials", "secrets"],
    },
    "errors": {
        "webhook_path": "/webhook/errors",
    },
    "github": {
        "auto_create_pr": True,
        "base_branch": "main",
        "pr_labels": ["auto-fix", "needs-review"],
    },
}


class DecisionsSearchConfig:
    def __init__(self, raw: dict[str, Any]):
        self._raw = raw

    def get(self, *path: str, default: Any = None) -> Any:
        node = self._raw
        for key in path:
            if not isinstance(node, dict) or not isinstance(key, str):
                return default
            node = node.get(key)
            if node is None:
                return default
        return node

    @property
    def mode(self) -> str:
        return self.get("mode", default="light")

    @property
    def data_dir(self) -> str:
        return self.get("data_dir", default="data")

    @property
    def agent_provider(self) -> str:
        return self.get("agent", "provider", default="opencode")

    @property
    def agent_config(self) -> dict:
        return self.get("agent", default=_DEFAULTS["agent"])

    @property
    def notifications(self) -> dict:
        return self.get("notifications", default={})

    @property
    def scheduler_config(self) -> dict:
        return self.get("scheduler", default=_DEFAULTS["scheduler"])

    @property
    def safety(self) -> dict:
        return self.get("safety", default=_DEFAULTS["safety"])

    @property
    def errors_config(self) -> dict:
        return self.get("errors", default={})

    @property
    def github_config(self) -> dict:
        return self.get("github", default=_DEFAULTS["github"])

    def agent_api_key(self) -> str:
        provider = self.agent_provider
        key = self.get("agent", provider, "api_key", default="")
        if key:
            return key
        env_map = {
            "codex": "OPENAI_API_KEY",
            "claude": "ANTHROPIC_API_KEY",
            "zai": "ZAI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
        }
        return os.environ.get(env_map.get(provider, ""), "")

    def as_dict(self) -> dict[str, Any]:
        return dict(self._raw)


def load_config(path: str | Path | None = None) -> DecisionsSearchConfig:
    search_paths = []
    if path is not None:
        search_paths.append(Path(path))
    else:
        search_paths = [
            Path("decisionssearch.yaml"),
            Path("config/decisionssearch.yaml"),
        ]

    raw: dict[str, Any] = {}
    loaded_from = None
    for p in search_paths:
        if p.exists():
            with p.open() as f:
                raw = yaml.safe_load(f) or {}
            loaded_from = str(p)
            break

    if loaded_from:
        logger.info("Loaded config from %s", loaded_from)
    else:
        logger.info("No decisionssearch.yaml found — using defaults")

    raw = _resolve_env(raw)
    merged = _deep_merge(_DEFAULTS, raw)
    config = DecisionsSearchConfig(merged)

    # Safety: warn if webhook is exposed without authentication
    webhook_secret = config.errors_config.get("webhook_secret", "")
    if not webhook_secret:
        logger.warning(
            "Webhook secret is empty — webhook endpoint will reject all requests. "
            "Set 'errors.webhook_secret' in decisionssearch.yaml to a strong random value "
            "(generate: openssl rand -hex 32)"
        )

    return config
