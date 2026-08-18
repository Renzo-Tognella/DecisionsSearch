from __future__ import annotations

from decisionssearch.domain.memory_ledger import (
    MemoryRevision,
    RevisionState,
    legacy_memory_id_for_family,
)
from decisionssearch.application.governance.weight_service import WeightService


def _effective_weight(content) -> float:  # noqa: ANN001
    manual = content.weight_manual if content.weight_manual is not None else 0.5
    service = WeightService(config=WeightService().get_priority_config(content.category))
    return service.calculate_effective_weight(
        weight_manual=manual,
        weight_confidence=content.weight_confidence,
        weight_usage=content.weight_usage,
        weight_feedback=content.weight_feedback,
        weight_contextual=content.weight_contextual,
        last_accessed_at=content.last_accessed_at,
        significance=content.significance,
    )


def revision_to_legacy_view(
    revision: MemoryRevision,
    state: RevisionState = RevisionState.ACTIVE,
    memory_id: str = "",
) -> dict:
    """Projeção de leitura compatível; nunca é usada como fonte de escrita."""

    content = revision.content
    legacy_ids = dict(content.legacy_ids)
    stable_memory_id = (
        memory_id
        or legacy_ids.get("memory_id")
        or legacy_ids.get("episode_id")
        or legacy_ids.get("procedure_id")
        or legacy_memory_id_for_family(revision.family_id)
    )
    return {
        "memory_id": stable_memory_id,
        "family_id": str(revision.family_id),
        "revision_id": str(revision.revision_id),
        "project": content.project,
        "category": content.category,
        "type": content.category,
        "branch": content.memory_branch,
        "domain": list(content.domain),
        "modules": list(content.modules),
        "title": content.title,
        "summary": content.summary,
        "details": content.details,
        "objective": content.objective,
        "trigger": content.trigger,
        "stakeholders": list(content.stakeholders),
        "action_triggers": list(content.action_triggers),
        "related_files": list(content.related_files),
        "business_rules": list(content.business_rules),
        "architectural_rationale": content.architectural_rationale,
        "examples": list(content.examples),
        "alternatives_considered": list(content.alternatives_considered),
        "status": state.value,
        "weight_manual": content.weight_manual if content.weight_manual is not None else 0.5,
        "effective_weight": _effective_weight(content),
        "significance": content.significance,
        "weight_confidence": content.weight_confidence,
        "weight_usage": content.weight_usage,
        "weight_feedback": content.weight_feedback,
        "weight_contextual": content.weight_contextual,
        "last_accessed_at": content.last_accessed_at.isoformat() if content.last_accessed_at else None,
        "created_at": revision.created_at.isoformat(),
        "updated_at": revision.created_at.isoformat(),
        "event_date": content.valid_from.isoformat() if content.valid_from else None,
        "valid_at": content.valid_from.isoformat() if content.valid_from else revision.created_at.isoformat(),
        "invalid_at": content.valid_to.isoformat() if content.valid_to else None,
        "source_hash": revision.content_hash,
        "content_hash": revision.content_hash,
        "evidence_count": len(revision.evidence_ids),
    }
