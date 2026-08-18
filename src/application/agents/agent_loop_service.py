from __future__ import annotations

import logging
from dataclasses import dataclass, field

from decisionssearch.domain.episodic.episodic_memory import EpisodicMemory, EpisodeStatus
from decisionssearch.domain.memory.memory_item import MemoryItem
from decisionssearch.application.memory.admission_service import AdmissionService
from decisionssearch.application.memory.episodic_memory_service import EpisodicMemoryService
from decisionssearch.application.memory.extraction_service import ExtractionService
from decisionssearch.application.search.hybrid_search_service import HybridSearchService
from decisionssearch.infrastructure.persistence.neo4j.neo4j_service import Neo4jService
from decisionssearch.application.memory.persistence_service import PersistenceService
from decisionssearch.application.memory.procedural_memory_service import ProceduralMemoryService
from decisionssearch.application.governance.weight_service import WeightService
from decisionssearch.application.agents.cognitive_reflection_service import CognitiveReflectionService

logger = logging.getLogger(__name__)


@dataclass
class TaskState:
    """Estado rastreado durante um ciclo cognitivo completo."""

    project: str = ""
    domain: str | None = None
    retrieved_memory_ids: list[str] = field(default_factory=list)
    served_procedure_ids: list[str] = field(default_factory=list)
    served_episode_ids: list[str] = field(default_factory=list)


class AgentLoopService:
    """Orquestra o ciclo cognitivo: PERCEIVE → ACT → LEARN.

    Integra memória semântica (search), episódica (episódios passados),
    e procedural (passos reutilizáveis) em um loop coeso.
    """

    MAX_CONTEXT_ITEMS = 3
    MAX_SUMMARY_CHARS = 200
    MAX_EPISODES = 3
    MAX_PROCEDURES = 2

    def __init__(
        self,
        search: HybridSearchService,
        extraction: ExtractionService,
        admission: AdmissionService,
        persistence: PersistenceService,
        episodic_memory: EpisodicMemoryService | None = None,
        procedural_memory: ProceduralMemoryService | None = None,
        weight: WeightService | None = None,
        neo4j: Neo4jService | None = None,
        reflection_service: CognitiveReflectionService | None = None,
    ):
        self.search = search
        self.extraction = extraction
        self.admission = admission
        self.persistence = persistence
        self.episodic_memory = episodic_memory
        self.procedural_memory = procedural_memory
        self.weight = weight or WeightService()
        self.neo4j = neo4j
        self.reflection_service = reflection_service
        self._last_task_state: TaskState | None = None

    # ── PERCEIVE ─────────────────────────────────────────────

    async def pre_task_context(
        self, project: str, domain: str | None = None,
    ) -> dict:
        """Fase PERCEIVE: carrega contexto semântico, episódico e procedural."""
        state = TaskState(project=project, domain=domain)

        # Memória semântica (design rules, patterns, ADRs)
        context = await self._load_semantic_context(project, domain)

        # Memória episódica (tarefas passadas similares)
        episodes = await self._load_recent_episodes(project)
        if episodes:
            context["past_episodes"] = episodes
            state.served_episode_ids = [
                ep.get("episode_id", "") for ep in episodes
            ]

        # Memória procedural (procedimentos com melhor success_rate)
        procedures = await self._load_best_procedures(project)
        if procedures:
            context["procedures"] = procedures
            state.served_procedure_ids = [
                p.get("procedure_id", "") for p in procedures
            ]

        # Rastreia memory_ids servidos para reinforcement posterior
        state.retrieved_memory_ids = self._extract_memory_ids(context)

        self._last_task_state = state
        logger.info(
            "PERCEIVE: %d memórias, %d episódios, %d procedimentos para %s",
            len(state.retrieved_memory_ids),
            len(state.served_episode_ids),
            len(state.served_procedure_ids),
            project,
        )
        return self.compact_context(context)

    async def _load_semantic_context(
        self, project: str, domain: str | None,
    ) -> dict:
        context: dict = {
            "feature_descriptions": await self.search.search(
                query_text="feature flow trigger stakeholders related files",
                project=project,
                category="FeatureDescription",
                top_k=5,
            ),
            "design_rules": await self.search.search(
                query_text="design rules conventions",
                project=project,
                category="DesignRule",
                top_k=5,
            ),
            "patterns": await self.search.search(
                query_text="design patterns",
                project=project,
                category="DesignPattern",
                top_k=5,
            ),
            "architectural_decisions": await self.search.search(
                query_text="architectural decisions",
                project=project,
                category="ArchitecturalDecision",
                top_k=5,
            ),
        }
        if domain:
            context["domain_rules"] = await self.search.search(
                query_text=f"business rules {domain}",
                project=project,
                category="BusinessRule",
                top_k=5,
            )
        return context

    async def _load_recent_episodes(
        self, project: str,
    ) -> list[dict]:
        """Carrega episódios recentes, priorizando falhas."""
        if not self.episodic_memory:
            return []
        try:
            failed = await self.episodic_memory.query_episodes(
                project=project, outcome="failed", limit=2,
            )
            recent = await self.episodic_memory.query_episodes(
                project=project, limit=self.MAX_EPISODES,
            )
            seen = {ep.get("episode_id") for ep in failed}
            combined = list(failed)
            for ep in recent:
                if ep.get("episode_id") not in seen:
                    combined.append(ep)
                if len(combined) >= self.MAX_EPISODES:
                    break
            return [
                {
                    "episode_id": ep.get("episode_id", ""),
                    "task_description": str(
                        ep.get("task_description", "")
                    )[:self.MAX_SUMMARY_CHARS],
                    "outcome": ep.get("outcome", ""),
                    "lessons": ep.get("lessons", [])[:3],
                }
                for ep in combined
            ]
        except Exception as error:
            logger.warning("Falha ao carregar episódios: %s", error)
            return []

    async def _load_best_procedures(
        self, project: str,
    ) -> list[dict]:
        """Carrega procedimentos com maior success_rate."""
        if not self.procedural_memory:
            return []
        try:
            procs = await self.procedural_memory.query_procedures(
                project=project, limit=self.MAX_PROCEDURES,
            )
            return [
                {
                    "procedure_id": p.get("procedure_id", ""),
                    "task_type": p.get("task_type", ""),
                    "steps": p.get("steps", []),
                    "success_rate": p.get("success_rate", 0.0),
                    "usage_count": p.get("usage_count", 0),
                }
                for p in procs
            ]
        except Exception as error:
            logger.warning("Falha ao carregar procedimentos: %s", error)
            return []

    @staticmethod
    def _extract_memory_ids(context: dict) -> list[str]:
        ids: list[str] = []
        for items in context.values():
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and item.get("memory_id"):
                    ids.append(item["memory_id"])
        return ids

    # ── ACT (mid-task) ───────────────────────────────────────

    async def during_task_query(
        self, question: str, project: str,
    ) -> list[dict]:
        """Fase ACT: busca semântica ad-hoc durante a execução."""
        results = await self.search.search(
            query_text=question, project=project, top_k=5,
        )
        if self._last_task_state:
            for item in results:
                mid = item.get("memory_id")
                if mid and mid not in self._last_task_state.retrieved_memory_ids:
                    self._last_task_state.retrieved_memory_ids.append(mid)
        return results

    # ── LEARN ────────────────────────────────────────────────

    async def post_task_summary(
        self,
        task_description: str,
        changes: str,
        project: str,
        outcome: str = "completed",
    ) -> dict:
        """Fase LEARN: extrai conhecimento, cria episódio, reforça memórias."""
        full_text = f"TAREFA: {task_description}\n\nMUDANCAS: {changes}"
        candidates = await self.extraction.extract_candidates(
            full_text, project=project,
        )

        # Persiste candidatos via pipeline padrão
        results: list[dict] = []
        created_memory_ids: list[str] = []
        for candidate in candidates:
            result = await self._process_candidate(candidate)
            results.append(result)
            if result.get("memory_id"):
                created_memory_ids.append(result["memory_id"])

        summary = {
            "candidates_extracted": len(candidates),
            "memories_created": sum(
                1 for r in results if r.get("action") == "create" and r.get("status") == "active"
            ),
            "memories_updated": sum(
                1 for r in results if r.get("action") == "update" and r.get("status") == "active"
            ),
            "pending_proposals": sum(1 for r in results if r.get("status") == "pending_approval"),
            "rejected": sum(
                1 for r in results if r.get("status") == "rejected"
            ),
            "details": results,
        }

        lessons = []
        if self.reflection_service and self._last_task_state:
            reflection_result = await self.reflection_service.reflect_on_task(
                state=self._last_task_state,
                outcome=outcome,
                task_description=task_description,
                changes=changes,
            )
            lessons = reflection_result.get("lessons", [])
            summary["reflection"] = reflection_result

        reinforced = 0
        procedures_updated = 0
        if not self.reflection_service:
            reinforced = await self._reinforce_retrieved_memories(outcome=outcome)
            if reinforced:
                summary["reinforced_memories"] = reinforced

            procedures_updated = await self._update_procedure_usage(outcome=outcome)
            if procedures_updated:
                summary["procedures_updated"] = procedures_updated

        episode_result = await self._create_episode(
            task_description=task_description,
            changes=changes,
            project=project,
            outcome=outcome,
            related_memory_ids=created_memory_ids,
            lessons=lessons,
        )
        if episode_result:
            summary["episode"] = episode_result

        self._last_task_state = None
        logger.info(
            "LEARN: %d candidatos, %d criados, episódio=%s, "
            "%d reforçados, %d procedimentos atualizados",
            len(candidates),
            summary["memories_created"],
            bool(episode_result),
            reinforced,
            procedures_updated,
        )
        return summary

    async def _process_candidate(self, candidate) -> dict:
        """Pipeline de admissão + persistência para um candidato."""
        try:
            admission_result = await self.admission.evaluate(candidate)
            if admission_result.status in ("active", "proposed"):
                item = await self.persistence.persist(
                    candidate,
                    admission_result.model_dump()
                    if hasattr(admission_result, "model_dump")
                    else admission_result.__dict__,
                )
                if isinstance(item, dict):
                    return {
                        "memory_id": item.get("memory_id"),
                        "proposal_id": item.get("proposal_id"),
                        "title": candidate.title,
                        "action": admission_result.action,
                        "status": "pending_approval",
                        "reason": admission_result.reason,
                        "requires_human_approval": True,
                    }
                is_proposal = str(item.memory_id).startswith("proposal:")
                return {
                    "memory_id": None if is_proposal else item.memory_id,
                    "proposal_id": str(item.memory_id).split(":", 1)[1] if is_proposal else None,
                    "title": item.title,
                    "action": admission_result.action,
                    "status": "pending_approval" if is_proposal else admission_result.status,
                    "reason": admission_result.reason,
                    "requires_human_approval": is_proposal,
                }
            return {
                "title": candidate.title,
                "action": admission_result.action,
                "status": admission_result.status,
                "reason": admission_result.reason,
            }
        except Exception as error:
            return {
                "title": candidate.title,
                "action": "error",
                "status": "error",
                "reason": str(error),
            }

    async def _create_episode(
        self,
        task_description: str,
        changes: str,
        project: str,
        outcome: str,
        related_memory_ids: list[str],
        lessons: list[str] | None = None,
    ) -> dict | None:
        if not self.episodic_memory:
            return None
        try:
            status_map = {
                "completed": EpisodeStatus.COMPLETED,
                "failed": EpisodeStatus.FAILED,
                "partial": EpisodeStatus.PARTIAL,
            }
            episode = EpisodicMemory(
                episode_id=MemoryItem.generate_id(
                    project, "episode", task_description,
                ),
                project=project,
                task_description=task_description[:500],
                approach=changes[:500],
                outcome=status_map.get(outcome, EpisodeStatus.COMPLETED),
                lessons=lessons or [],
                related_memory_ids=related_memory_ids,
                tags=[outcome],
            )
            return await self.episodic_memory.create_episode(episode)
        except Exception as error:
            logger.warning("Falha ao criar episódio: %s", error)
            return None

    async def _reinforce_retrieved_memories(
        self, outcome: str,
    ) -> int:
        """Reforça pesos das memórias que foram servidas e a tarefa deu certo."""
        state = self._last_task_state
        if not state or not state.retrieved_memory_ids:
            return 0
        if not self.neo4j:
            return 0

        was_accepted = outcome in ("completed", "partial")
        reinforced = 0

        for memory_id in state.retrieved_memory_ids:
            try:
                mem = await self.neo4j.get_memory(memory_id)
                if not mem:
                    continue
                w_manual = float(mem.get("weight_manual", 0.5) or 0.5)
                w_usage = float(mem.get("weight_usage", 0.0) or 0.0)
                new_manual, new_usage = self.weight.reinforce_on_retrieval(
                    weight_manual=w_manual,
                    weight_usage=w_usage,
                    was_accepted=was_accepted,
                )
                category = str(mem.get("category", "DesignPattern"))
                config = self.weight.get_priority_config(category)
                new_effective = self.weight.calculate_effective_weight(
                    weight_manual=new_manual,
                    weight_confidence=float(
                        mem.get("weight_confidence", 0.5) or 0.5
                    ),
                    weight_usage=new_usage,
                    weight_feedback=float(
                        mem.get("weight_feedback", 0.0) or 0.0
                    ),
                    significance=float(mem.get("significance", 0.5) or 0.5),
                    config=config,
                )
                await self.neo4j.set_weight(
                    memory_id, new_manual, new_effective,
                )
                reinforced += 1
            except Exception as error:
                logger.warning(
                    "Falha ao reforçar memória %s: %s", memory_id, error,
                )
        return reinforced

    async def _update_procedure_usage(self, outcome: str) -> int:
        """Atualiza success_rate dos procedimentos servidos."""
        state = self._last_task_state
        if not state or not state.served_procedure_ids:
            return 0
        if not self.procedural_memory:
            return 0

        success = outcome in ("completed",)
        updated = 0
        for proc_id in state.served_procedure_ids:
            if not proc_id:
                continue
            try:
                await self.procedural_memory.record_usage(
                    proc_id, success=success,
                )
                updated += 1
            except Exception as error:
                logger.warning(
                    "Falha ao atualizar procedimento %s: %s",
                    proc_id, error,
                )
        return updated

    # ── UTILITIES ────────────────────────────────────────────

    def compact_context(self, context: dict) -> dict:
        compacted = {}
        for section, items in context.items():
            if not isinstance(items, list):
                compacted[section] = items
                continue
            ranked = sorted(
                items,
                key=lambda x: float(
                    x.get("effective_weight", 0.0)
                    if isinstance(x, dict) else 0
                ),
                reverse=True,
            )
            trimmed = []
            for item in ranked[:self.MAX_CONTEXT_ITEMS]:
                if isinstance(item, dict):
                    trimmed.append(
                        {
                            "memory_id": item.get("memory_id", ""),
                            "title": item.get("title", ""),
                            "summary": str(
                                item.get("summary", "")
                            )[:self.MAX_SUMMARY_CHARS],
                            "effective_weight": item.get(
                                "effective_weight", 0.0,
                            ),
                        }
                    )
                else:
                    trimmed.append(item)
            compacted[section] = trimmed
        return compacted
