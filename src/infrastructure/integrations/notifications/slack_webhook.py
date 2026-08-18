from __future__ import annotations

import httpx


class SlackWebhookChannel:
    def __init__(self, config: dict) -> None:
        self._webhook_url = config["webhook_url"]

    @property
    def name(self) -> str:
        return "slack"

    async def send(self, notification: dict) -> bool:
        blocks = self._to_blocks(notification)
        async with httpx.AsyncClient() as client:
            resp = await client.post(self._webhook_url, json={"blocks": blocks})
            return resp.status_code == 200

    async def health_check(self) -> bool:
        return self._webhook_url.startswith("https://hooks.slack.com/")

    async def close(self) -> None:
        pass

    @staticmethod
    def _to_blocks(notification: dict) -> list[dict]:
        severity_emoji = {"critical": "\U0001f534", "error": "\U0001f7e0", "warning": "\U0001f7e1", "info": "\U0001f535"}
        emoji = severity_emoji.get(notification.get("severity", "info"), "\U0001f535")

        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": f"{emoji} {notification.get('title', '')}"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": notification.get("body", "")[:3000]}},
        ]

        urls = notification.get("urls", [])
        if urls:
            elements = [
                {"type": "button", "text": {"type": "plain_text", "text": u.get("label", "Link")[:75]}, "url": u["url"]}
                for u in urls[:5]
            ]
            blocks.append({"type": "actions", "elements": elements})

        meta = notification.get("metadata", {})
        parts = []
        if meta.get("service"):
            parts.append(f"*Service:* {meta['service']}")
        if meta.get("error_type"):
            parts.append(f"*Error:* {meta['error_type']}")
        if parts:
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": " | ".join(parts)}]})

        return blocks
