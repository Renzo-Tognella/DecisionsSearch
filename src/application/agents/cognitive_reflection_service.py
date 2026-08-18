from __future__ import annotations

import json
from datetime import datetime

class CognitiveReflectionService:
    def __init__(
        self,
        neo4j,
        procedural_memory=None,
        weight_service=None,
        telemetry=None,
        extraction=None,
        proposal_service=None,
        ledger=None,
    ):
        self.neo4j = neo4j
        self.procedural_memory = procedural_memory
        self.weight_service = weight_service
        self.telemetry = telemetry
        self.extraction = extraction
        self.proposal_service = proposal_service
        self.ledger = ledger

    async def reflect_on_task(
        self,
        state,
        outcome: str,
        task_description: str,
        changes: str,
    ) -> dict:
        success = outcome == "completed"
        if self.procedural_memory and state.served_procedure_ids:
            for proc_id in state.served_procedure_ids:
                if proc_id:
                    await self.procedural_memory.record_usage(proc_id, success=success)
        
        weight_changes = []
        if state.retrieved_memory_ids:
            weight_changes = await self._calibrate_memories(state.retrieved_memory_ids, outcome)
            
        lessons = await self.extract_lessons(task_description, changes, outcome)
        return {"status": "reflected", "lessons": lessons, "weight_changes_proposed": weight_changes}

    async def _calibrate_memories(self, memory_ids: list[str], outcome: str) -> list[dict]:
        proposed: list[dict] = []
        if (not self.neo4j and not self.ledger) or not self.weight_service:
            return proposed
            
        success = outcome in ("completed", "partial")
        for mid in memory_ids:
            if not mid:
                continue
            revision = None
            if self.ledger is not None:
                alias = await self.ledger.resolve_alias(mid)
                if alias is None or alias.family_id is None:
                    continue
                family = await self.ledger.get_family(alias.family_id)
                if family is None:
                    continue
                head = await self.ledger.get_head(
                    alias.family_id,
                    family.memory_scope,
                    alias.memory_branch,
                )
                revision = await self.ledger.get_revision(head.revision_id) if head else None
                if revision is None:
                    continue
                mem = {
                    "memory_id": mid,
                    "category": revision.content.category,
                    "weight_manual": revision.content.weight_manual,
                    "weight_usage": revision.content.weight_usage,
                    "weight_feedback": revision.content.weight_feedback,
                    "weight_confidence": revision.content.weight_confidence,
                    "weight_contextual": revision.content.weight_contextual,
                    "significance": revision.content.significance,
                    "last_accessed_at": revision.content.last_accessed_at,
                }
            else:
                mem = await self.neo4j.get_memory(mid)
            if not mem:
                continue
                
            w_manual = float(mem.get("weight_manual", 0.5) or 0.5)
            w_usage = float(mem.get("weight_usage", 0.0) or 0.0)
            w_feedback = float(mem.get("weight_feedback", 0.0) or 0.0)
            w_confidence = float(mem.get("weight_confidence", 0.5) or 0.5)
            w_contextual = float(mem.get("weight_contextual", 0.5) or 0.5)
            significance = float(mem.get("significance", 0.5) or 0.5)
            last_accessed_at = mem.get("last_accessed_at")
            if isinstance(last_accessed_at, str):
                try:
                    last_accessed_at = datetime.fromisoformat(last_accessed_at.replace("Z", "+00:00"))
                except ValueError:
                    last_accessed_at = None
            
            category = str(mem.get("category", "DesignPattern"))
            config = self.weight_service.get_priority_config(category)
            
            if outcome == "failed":
                new_feedback = self.weight_service.update_on_feedback(w_feedback, 0.0)
                new_manual = w_manual
                new_usage = w_usage
                if self.telemetry:
                    self.telemetry.record_rejection(mid, reason="task_failure")
            else:
                new_manual, new_usage = self.weight_service.reinforce_on_retrieval(
                    weight_manual=w_manual,
                    weight_usage=w_usage,
                    was_accepted=success,
                )
                new_feedback = self.weight_service.update_on_feedback(w_feedback, 1.0)
                if self.telemetry:
                    self.telemetry.record_acceptance(mid)
                    
            new_effective = self.weight_service.calculate_effective_weight(
                weight_manual=new_manual,
                weight_confidence=w_confidence,
                weight_usage=new_usage,
                weight_feedback=new_feedback,
                weight_contextual=w_contextual,
                last_accessed_at=last_accessed_at,
                significance=significance,
                config=config,
            )
            if self.proposal_service is not None and self.ledger is not None and revision is not None:
                updated_content = revision.content.model_copy(
                    update={
                        "weight_manual": new_manual,
                        "weight_usage": new_usage,
                        "weight_feedback": new_feedback,
                    }
                )
                proposal = await self.proposal_service.propose_update(
                    revision.family_id,
                    updated_content,
                    requested_by="reflection",
                    reason=f"Calibração pós-tarefa ({outcome}) da memória {mid}",
                    idempotency_key=f"reflection:{mid}:{revision.revision_id}:{outcome}",
                )
                proposed.append(
                    {
                        "memory_id": mid,
                        "proposal_id": str(proposal.proposal_id),
                        "status": proposal.status.value,
                        "preview_hash": proposal.preview_hash,
                        "before": {
                            "weight_manual": w_manual,
                            "weight_usage": w_usage,
                            "weight_feedback": w_feedback,
                        },
                        "after": {
                            "weight_manual": new_manual,
                            "weight_usage": new_usage,
                            "weight_feedback": new_feedback,
                            "effective_weight": new_effective,
                        },
                        "requires_human_approval": True,
                        "question": "A alteração derivada de peso faz sentido?",
                    }
                )
                continue
            if self.proposal_service is not None:
                proposed.append(
                    {
                        "memory_id": mid,
                        "status": "pending_approval",
                        "before": {
                            "weight_manual": w_manual,
                            "weight_usage": w_usage,
                            "weight_feedback": w_feedback,
                        },
                        "after": {
                            "weight_manual": new_manual,
                            "weight_usage": new_usage,
                            "weight_feedback": new_feedback,
                            "effective_weight": new_effective,
                        },
                        "requires_human_approval": True,
                        "question": "A alteração derivada de peso faz sentido?",
                    }
                )
                continue
            await self.neo4j.set_weight(mid, new_manual, new_effective)
        return proposed

    async def extract_lessons(
        self,
        task_description: str,
        changes: str,
        outcome: str,
    ) -> list[str]:
        if not self.extraction or not hasattr(self.extraction, "client") or not self.extraction.client:
            return [f"Analise manual de resultado {outcome}"]
            
        prompt = f"Outcome: {outcome}\nTask: {task_description}\nChanges: {changes}\nExtraia licoes aprendidas como JSON list de strings: {{\"lessons\": [\"...\"]}}"
        try:
            response = await self.extraction.client.chat.completions.create(
                model=self.extraction.model,
                messages=[
                    {"role": "system", "content": "Voce e um assistente analitico focado em licoes aprendidas."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=150,
            )
            data = json.loads(response.choices[0].message.content.strip())
            return data.get("lessons", [])
        except Exception:
            return [f"Erro na extracao automatica de licoes para {outcome}"]
