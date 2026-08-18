from __future__ import annotations

import hashlib
import hmac
import json

import httpx


class GenericWebhookChannel:
    def __init__(self, config: dict) -> None:
        self._url = config["url"]
        self._secret = config.get("secret", "")
        self._headers = config.get("headers", {})

    @property
    def name(self) -> str:
        return "generic_webhook"

    async def send(self, notification: dict) -> bool:
        body = json.dumps(notification, default=str)
        headers = {"Content-Type": "application/json", **self._headers}
        if self._secret:
            sig = hmac.new(self._secret.encode(), body.encode(), hashlib.sha256).hexdigest()
            headers["X-DecisionsSearch-Signature"] = f"sha256={sig}"

        async with httpx.AsyncClient() as client:
            resp = await client.post(self._url, content=body, headers=headers, timeout=10.0)
            return resp.status_code in (200, 201, 202, 204)

    async def health_check(self) -> bool:
        return bool(self._url)

    async def close(self) -> None:
        pass
