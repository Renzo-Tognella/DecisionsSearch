"""Fachadas de modelos legados sobre o ledger versionado.

Os modelos EpisodicMemory, ProceduralMemory e PRMemory continuam sendo úteis
para quem consome a API, mas não são mais writers canônicos quando o ledger
está configurado. Este módulo concentra a conversão e o envelope de proposta.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from decisionssearch.domain import EpisodicMemory, PRMemory, ProceduralMemory
from decisionssearch.domain.memory_ledger import MemoryContent, MemoryRevision, MemoryScope


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: str) -> datetime | None:
    if not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def pending_envelope(proposal, *, legacy_id: str = "", revision: MemoryRevision | None = None) -> dict:  # noqa: ANN001
    if revision is not None or proposal.status.value == "applied":
        if revision is not None:
            return {
                **applied_envelope(revision, legacy_id=legacy_id),
                "proposal_id": str(proposal.proposal_id),
            }
    return {
        "status": "pending_approval",
        "proposal_id": str(proposal.proposal_id),
        "preview_hash": proposal.preview_hash,
        "proposed_legacy_id": legacy_id,
        "memory_id": None,
        "family_id": None,
        "revision_id": None,
        "requires_human_approval": True,
        "before": [item.model_dump(mode="json") for item in proposal.before],
        "after": proposal.after.model_dump(mode="json") if proposal.after else None,
        "field_diff": [item.model_dump(mode="json") for item in proposal.field_diff],
        "reason": proposal.reason,
    }


def applied_envelope(revision: MemoryRevision, *, legacy_id: str = "") -> dict:
    return {
        "status": "applied",
        "proposal_id": None,
        "preview_hash": None,
        "proposed_legacy_id": legacy_id,
        "memory_id": legacy_id,
        "family_id": str(revision.family_id),
        "revision_id": str(revision.revision_id),
        "content_hash": revision.content_hash,
        "requires_human_approval": False,
        "before": None,
        "after": revision.content.model_dump(mode="json"),
        "field_diff": [],
        "reason": "",
    }


def episode_to_content(episode: EpisodicMemory) -> MemoryContent:
    payload = episode.model_dump(mode="json")
    return MemoryContent(
        project=episode.project,
        category="EpisodicMemory",
        title=episode.task_description[:200],
        summary=f"{episode.outcome.value}: {episode.task_description}",
        details=episode.approach,
        objective=episode.task_description,
        memory_scope=MemoryScope.EPISODIC,
        memory_branch="episodic",
        payload_schema="episodic.v1",
        structured_payload=payload,
        legacy_ids={"episode_id": episode.episode_id},
        valid_from=episode.created_at,
    )


def procedure_to_content(procedure: ProceduralMemory) -> MemoryContent:
    payload = procedure.model_dump(mode="json")
    return MemoryContent(
        project=procedure.project,
        category="ProceduralMemory",
        title=procedure.task_type,
        summary=(procedure.steps[0] if procedure.steps else procedure.task_type),
        details="\n".join(procedure.steps),
        objective=procedure.task_type,
        business_rules=tuple(procedure.preconditions),
        modules=tuple(procedure.tools_required),
        memory_scope=MemoryScope.PROCEDURAL,
        memory_branch="procedural",
        payload_schema="procedural.v1",
        structured_payload=payload,
        legacy_ids={"procedure_id": procedure.procedure_id},
        valid_from=procedure.created_at,
    )


def pr_to_content(memory: PRMemory) -> MemoryContent:
    payload = memory.model_dump(mode="json")
    return MemoryContent(
        project=memory.project,
        category="PullRequestMemory",
        title=memory.title,
        summary=memory.summary,
        details=memory.work_item_summary,
        objective=memory.objective,
        domain=tuple(memory.areas),
        related_files=tuple(memory.changed_files),
        stakeholders=tuple(memory.authors),
        memory_scope=MemoryScope.PULL_REQUEST,
        memory_branch="pull_request",
        payload_schema="pull_request.v1",
        structured_payload=payload,
        legacy_ids={"memory_id": memory.memory_id},
        valid_from=_parse_datetime(memory.event_date),
    )


def hydrate_legacy(revision: MemoryRevision) -> dict[str, Any]:
    payload = revision.content.structured_payload or {}
    schema = revision.content.payload_schema or ""
    if schema == "episodic.v1":
        value = EpisodicMemory.model_validate(payload).model_dump(mode="json")
    elif schema == "procedural.v1":
        value = ProceduralMemory.model_validate(payload).model_dump(mode="json")
    elif schema == "pull_request.v1":
        value = PRMemory.model_validate(payload).model_dump(mode="json")
        value["pr_status"] = value.pop("status", "open")
    else:
        if revision.content.memory_scope is not MemoryScope.SEMANTIC:
            raise ValueError(
                f"schema de payload desconhecido para {revision.content.memory_scope.value}: {schema or '<empty>'}"
            )
        value = revision.content.model_dump(mode="json")
    value.update(
        {
            "family_id": str(revision.family_id),
            "revision_id": str(revision.revision_id),
            "content_hash": revision.content_hash,
            "memory_scope": revision.content.memory_scope.value,
            "memory_branch": revision.content.memory_branch,
        }
    )
    return value
