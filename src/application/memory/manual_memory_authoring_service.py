from __future__ import annotations

from datetime import datetime

from decisionssearch.domain import CreateManualMemoryCommand, EvidenceRef, MemoryCandidate
from decisionssearch.domain.shared.exceptions import AdmissionError
from decisionssearch.application.memory.admission_service import AdmissionService
from decisionssearch.application.memory.persistence_service import PersistenceService


class ManualMemoryAuthoringService:
    """Autor de memoria manual que reaproveita admissao e persistencia canonicas."""

    def __init__(
        self,
        admission: AdmissionService,
        persistence: PersistenceService,
        proposal_service=None,  # noqa: ANN001
    ):
        self.admission = admission
        self.persistence = persistence
        self.proposal_service = proposal_service

    @staticmethod
    def _parse_event_date(raw: str) -> datetime | None:
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    async def create_manual_memory(self, command: CreateManualMemoryCommand):  # noqa: ANN201
        candidate = MemoryCandidate(
            project=command.project,
            type=command.category,
            domain=command.domain,
            modules=command.modules,
            title=command.title,
            summary=command.summary,
            details=command.details,
            objective=command.objective,
            trigger=command.trigger,
            stakeholders=command.stakeholders,
            action_triggers=command.action_triggers,
            related_files=command.related_files,
            business_rules=command.business_rules,
            architectural_rationale=command.architectural_rationale,
            examples=command.examples,
            alternatives_considered=command.alternatives_considered,
            event_date=self._parse_event_date(command.event_date),
            evidence=[
                EvidenceRef(
                    type="manual",
                    ref=f"{command.project}:{command.category}:{command.title}",
                    snippet=command.summary,
                )
            ],
        )
        admission_result = await self.admission.evaluate(candidate)
        status = self._admission_field(admission_result, "status")
        action = self._admission_field(admission_result, "action")

        if status not in {"active", "proposed"} or action not in {"create", "update", "refine"}:
            raise AdmissionError(
                "A autoria manual foi rejeitada pela admissao",
                gate="manual_authoring",
                candidate_title=candidate.title,
                context={
                    "project": candidate.project,
                    "category": candidate.type,
                    "status": status,
                    "action": action,
                    "reason": self._admission_field(admission_result, "reason"),
                },
            )

        if self.proposal_service is not None:
            proposal = await self.proposal_service.propose_candidate(
                candidate,
                admission_result,
                requested_by="agent",
                reason="Autoria manual requer aprovação explícita",
            )
            after = proposal.after.model_dump(mode="json") if proposal.after else None
            return {
                "proposal_id": str(proposal.proposal_id),
                "family_id": str(proposal.target_family_id) if proposal.target_family_id else None,
                "revision_id": None,
                "memory_id": None,
                "status": proposal.status.value,
                "requires_human_approval": True,
                "preview_hash": proposal.preview_hash,
                "before": [item.model_dump(mode="json") for item in proposal.before],
                "after": after,
                "field_diff": [item.model_dump(mode="json") for item in proposal.field_diff],
                "evidence": [item.model_dump(mode="json") for item in proposal.evidence],
                "reason": proposal.reason,
                "question": "A alteração faz sentido e deve ser aprovada?",
                **(after or {}),
            }

        return await self.persistence.persist(candidate, admission_result)

    @staticmethod
    def _admission_field(admission_result: object, field: str) -> str:
        if isinstance(admission_result, dict):
            return str(admission_result.get(field, ""))
        return str(getattr(admission_result, field, ""))
