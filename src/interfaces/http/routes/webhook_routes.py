from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from decisionssearch.domain.incidents.error_event import ErrorEvent

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])


class ErrorWebhookPayload(BaseModel):
    error_type: str
    error_message: str
    stack_trace: str = ""
    service: str = ""
    environment: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


def _container(request: Request) -> Any:
    return request.app.state.container


def _verify_signature(body: bytes, secret: str, signature: str | None) -> bool:
    """Verify HMAC-SHA256 webhook signature.

    IMPORTANT: If no secret is configured, ALL requests are rejected.
    The webhook_secret MUST be set to a strong random value in production.
    Generate one with: openssl rand -hex 32
    """
    if not secret:
        logger.warning("Webhook secret is empty — rejecting all requests. Set 'errors.webhook_secret' in config.")
        return False
    if not signature:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/webhook/errors")
async def ingest_error(payload: ErrorWebhookPayload, request: Request) -> dict:
    container = _container(request)
    orchestrator = getattr(container, "error_orchestrator", None)
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Error pipeline not configured")

    cfg = getattr(container, "config", {})
    errors_cfg = cfg.errors_config if hasattr(cfg, "errors_config") else {}
    webhook_secret = errors_cfg.get("webhook_secret", "")

    body = await request.body()
    sig = request.headers.get("X-Signature", "")
    if not _verify_signature(body, webhook_secret, sig if webhook_secret else None):
        raise HTTPException(status_code=401, detail="Invalid signature")

    event = ErrorEvent(
        error_type=payload.error_type,
        error_message=payload.error_message,
        stack_trace=payload.stack_trace,
        service=payload.service,
        environment=payload.environment,
        metadata=payload.metadata,
    )

    try:
        result = await orchestrator.handle_error(event)
        return {"status": "received", **result}
    except Exception as e:
        logger.exception("Error processing webhook")
        raise HTTPException(status_code=500, detail=str(e))
