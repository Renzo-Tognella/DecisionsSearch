from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from decisionssearch.application.notifications.notification_protocol import NotificationChannel
from decisionssearch.infrastructure.integrations.notifications.slack_webhook import SlackWebhookChannel
from decisionssearch.infrastructure.integrations.notifications.generic_webhook import GenericWebhookChannel

logger = logging.getLogger(__name__)

_ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")

BUILTIN_CHANNELS = {
    "slack": SlackWebhookChannel,
    "generic_webhook": GenericWebhookChannel,
}


def _resolve_env(value: Any) -> Any:
    if isinstance(value, str):
        def repl(m):
            return os.environ.get(m.group(1), "")
        return _ENV_VAR_RE.sub(repl, value)
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(v) for v in value]
    return value


@dataclass
class ChannelState:
    channel: NotificationChannel
    config: dict
    enabled: bool = True
    healthy: bool = False


@dataclass
class NotificationRegistry:
    channels: dict[str, ChannelState] = field(default_factory=dict)
    _closed: bool = False

    @classmethod
    def from_config(cls, config_path: str = "config/notifications.yaml") -> "NotificationRegistry":
        registry = cls()
        path = Path(config_path)
        if not path.exists():
            logger.debug("No notification config at %s", path)
            return registry
        with path.open() as f:
            config = yaml.safe_load(f) or {}
        config = _resolve_env(config)
        channels_cfg = config.get("channels", {})
        for name, cfg in channels_cfg.items():
            cfg = cfg if isinstance(cfg, dict) else {}
            factory = BUILTIN_CHANNELS.get(name)
            if factory is None:
                logger.warning("Channel '%s' not found", name)
                continue
            try:
                channel = factory(cfg)
                registry.channels[name] = ChannelState(
                    channel=channel, config=cfg,
                    enabled=cfg.get("enabled", True),
                )
                logger.info("Registered notification channel: %s", name)
            except Exception:
                logger.exception("Failed to create channel '%s'", name)
        return registry

    async def health_check_all(self) -> None:
        for key, state in self.channels.items():
            if not state.enabled:
                continue
            try:
                state.healthy = await state.channel.health_check()
            except Exception:
                state.healthy = False

    async def send_to_all(self, notification: dict) -> dict[str, bool]:
        results = {}
        for key, state in self.channels.items():
            if not state.enabled or not state.healthy:
                results[key] = False
                continue
            try:
                results[key] = await state.channel.send(notification)
            except Exception:
                logger.exception("Send failed for '%s'", key)
                results[key] = False
        return results

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for state in self.channels.values():
            try:
                await state.channel.close()
            except Exception:
                pass
