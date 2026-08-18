from __future__ import annotations

import logging
from uuid import uuid4

from decisionssearch.domain.shared.notification_envelope import (
    NotificationEnvelope, NotificationSeverity, NotificationType,
)
from decisionssearch.application.notifications.notification_registry import NotificationRegistry

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, registry: NotificationRegistry) -> None:
        self._registry = registry

    async def notify_error(
        self, service: str, error: str, severity: str = "error",
        related_prs: list[dict] | None = None, investigation_url: str = "",
    ) -> None:
        sev = NotificationSeverity(severity) if severity in NotificationSeverity else NotificationSeverity.ERROR
        envelope = NotificationEnvelope(
            notification_id=str(uuid4()),
            type=NotificationType.ERROR_ALERT,
            title=f"[{service}] Error detected",
            body=str(error)[:4000],
            severity=sev,
            url=investigation_url,
            urls=[
                {"label": f"PR #{p.get('pr_number', '?')}", "url": p.get("pr_url", "")}
                for p in (related_prs or [])
            ],
            metadata={"service": service, "related_prs": related_prs or []},
        )
        await self._registry.send_to_all(envelope.model_dump(mode="json"))

    async def notify_investigation(
        self, title: str, body: str, url: str = "", metadata: dict | None = None,
    ) -> None:
        envelope = NotificationEnvelope(
            notification_id=str(uuid4()),
            type=NotificationType.INVESTIGATION,
            title=title[:256],
            body=body[:4000],
            severity=NotificationSeverity.INFO,
            url=url,
            metadata=metadata or {},
        )
        await self._registry.send_to_all(envelope.model_dump(mode="json"))
