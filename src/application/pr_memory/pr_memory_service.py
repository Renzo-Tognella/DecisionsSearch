from __future__ import annotations

import hashlib
import math
import re

from decisionssearch.domain import CreatePRMemoryCommand, PRMemory, PRMemoryRelatedCandidate
from decisionssearch.application.memory.ledger.adapters import hydrate_legacy, pending_envelope, pr_to_content
from decisionssearch.domain.memory_ledger import MemoryScope
from decisionssearch.infrastructure.persistence.neo4j.neo4j_service import Neo4jService


def generate_pr_memory_id(project: str, repo: str, pr_number: int) -> str:
    seed = f"{project}:{repo}:{pr_number}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


class PRMemoryService:
    PR_MEMORY_RELATIONS = {"IMPLEMENTS", "EVIDENCES", "MODIFIES"}

    def __init__(self, neo4j: Neo4jService | None = None, embeddings=None, *, proposal_service=None, ledger=None):
        self.neo4j = neo4j
        self.embeddings = embeddings
        self.proposal_service = proposal_service
        self.ledger = ledger

    async def create_pr_memory(self, command: CreatePRMemoryCommand) -> dict:
        memory = PRMemory(
            memory_id=generate_pr_memory_id(
                command.project,
                command.repo,
                command.pr_number,
            ),
            **command.model_dump(),
        )
        if self.proposal_service is not None:
            proposal = await self.proposal_service.propose_create(
                pr_to_content(memory),
                requested_by="agent",
                reason="Registro de memória de pull request",
                idempotency_key=f"pr-memory:{memory.memory_id}",
            )
            revision = (
                await self.ledger.get_revision(proposal.applied_revision_id)
                if proposal.applied_revision_id and self.ledger is not None
                else None
            )
            return pending_envelope(proposal, legacy_id=memory.memory_id, revision=revision)
        if self.neo4j is None:
            raise RuntimeError("Serviço de PR sem ledger ou Neo4j")
        related_candidates = [
            PRMemoryRelatedCandidate.model_validate(item).model_dump(mode="json")
            for item in await self.neo4j.find_related_pr_candidates(memory)
        ]
        await self.neo4j.upsert_pr_memory(memory)
        payload = memory.model_dump(mode="json")
        payload["related_pr_candidates"] = related_candidates
        return payload

    async def link_pr_to_memory(
        self,
        pr_memory_id: str,
        memory_id: str,
        relation_type: str = "IMPLEMENTS",
        rationale: str = "",
    ) -> dict:
        relation_type = relation_type.strip().upper()
        if relation_type not in self.PR_MEMORY_RELATIONS:
            return {
                "error": "Unsupported PR relation type",
                "relation_type": relation_type,
                "status": "rejected",
            }
        if self.proposal_service is not None:
            source = await self.ledger.resolve_alias(pr_memory_id)
            target = await self.ledger.resolve_alias(memory_id)
            if source is None or source.family_id is None or target is None or target.family_id is None:
                return {"error": "Memory alias not found", "status": "quarantined"}
            proposal = await self.proposal_service.propose_link(
                source.family_id,
                target.family_id,
                relation_type,
                requested_by="agent",
                reason=rationale or "Relação de PR com memória canônica",
                idempotency_key=f"link:{pr_memory_id}:{memory_id}:{relation_type}",
            )
            return pending_envelope(proposal, legacy_id=pr_memory_id)
        if self.neo4j is None:
            raise RuntimeError("Serviço de PR sem ledger ou Neo4j")
        await self.neo4j.link_pr_to_memory(
            pr_memory_id=pr_memory_id,
            memory_id=memory_id,
            relation_type=relation_type,
            rationale=rationale,
        )

        return {
            "pr_memory_id": pr_memory_id,
            "memory_id": memory_id,
            "relation_type": relation_type,
            "status": "linked",
        }

    async def query_pr_linked_memories(self, pr_memory_id: str) -> list[dict]:
        if self.ledger is not None:
            alias = await self.ledger.resolve_alias(pr_memory_id)
            if alias is None or alias.family_id is None:
                return []
            rows = []
            for relation in await self.ledger.list_relations():
                if relation.source_family_id != alias.family_id:
                    continue
                revision = await self.ledger.get_revision(relation.target_revision_id) if relation.target_revision_id else None
                if revision is not None:
                    row = hydrate_legacy(revision)
                    row.update({"relation_type": relation.relation_type, "rationale": relation.rationale, "assertion_id": str(relation.assertion_id)})
                    rows.append(row)
            return rows
        if self.neo4j is None:
            return []
        return await self.neo4j.query_pr_linked_memories(pr_memory_id)

    async def query_memory_linked_prs(self, memory_id: str) -> list[dict]:
        if self.ledger is not None:
            alias = await self.ledger.resolve_alias(memory_id)
            if alias is None or alias.family_id is None:
                return []
            rows = []
            for relation in await self.ledger.list_relations():
                if relation.target_family_id != alias.family_id:
                    continue
                revision = await self.ledger.get_revision(relation.source_revision_id) if relation.source_revision_id else None
                if revision is not None:
                    row = hydrate_legacy(revision)
                    row.update({"relation_type": relation.relation_type, "rationale": relation.rationale, "assertion_id": str(relation.assertion_id)})
                    rows.append(row)
            return rows
        if self.neo4j is None:
            return []
        return await self.neo4j.query_memory_linked_prs(memory_id)

    async def query_pr_memories(
        self,
        project: str,
        repo: str | None = None,
        pr_number: int | None = None,
        changed_file_contains: str | None = None,
        summary_query: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        if self.ledger is not None:
            revisions = await self.ledger.list_effective_revisions(
                project=project,
                memory_scope=MemoryScope.PULL_REQUEST,
            )
            rows = []
            for revision in reversed(revisions):
                row = hydrate_legacy(revision)
                if repo is not None and row.get("repo") != repo:
                    continue
                if pr_number is not None and row.get("pr_number") != pr_number:
                    continue
                if changed_file_contains and not any(
                    changed_file_contains in item for item in row.get("changed_files", [])
                ):
                    continue
                rows.append(row)
            if not summary_query:
                return rows[:limit]
            return await self._rank_by_summary(summary_query, rows, limit=limit)
        if self.neo4j is None:
            raise RuntimeError("Serviço de PR sem ledger ou Neo4j")
        rows = await self.neo4j.query_pr_memories(
            project=project,
            repo=repo,
            pr_number=pr_number,
            changed_file_contains=changed_file_contains,
        )
        if not summary_query:
            return rows[:limit]
        return await self._rank_by_summary(summary_query, rows, limit=limit)

    async def get_pr_memory(self, memory_id: str) -> dict | None:
        """Retorna uma PR pela identidade legada, inclusive no ledger canônico."""
        if self.ledger is not None:
            alias = await self.ledger.resolve_alias(memory_id)
            if alias is None or alias.family_id is None:
                return None
            head = await self.ledger.get_head(
                alias.family_id,
                MemoryScope.PULL_REQUEST,
                alias.memory_branch,
            )
            revision = await self.ledger.get_revision(head.revision_id) if head else None
            return hydrate_legacy(revision) if revision is not None else None
        if self.neo4j is None:
            return None
        rows = await self.neo4j.execute_read(
            "MATCH (m:PRMemory {memory_id: $memory_id}) RETURN m { .* } AS pr",
            memory_id=memory_id,
        )
        return rows[0].get("pr") if rows else None

    async def _rank_by_summary(
        self,
        query: str,
        rows: list[dict],
        *,
        limit: int,
    ) -> list[dict]:
        if not rows:
            return []

        query_terms = self._terms(query)
        query_vector = None
        document_vectors: list[list[float]] = []
        if self.embeddings:
            try:
                query_vector = await self.embeddings.embed_query(query)
                document_vectors = await self.embeddings.embed_batch(
                    [self._summary_text(row) for row in rows]
                )
            except Exception:
                query_vector = None
                document_vectors = []

        scored: list[dict] = []
        for index, row in enumerate(rows):
            text = self._summary_text(row)
            lexical = self._lexical_overlap(query_terms, self._terms(text))
            dense = (
                self._cosine(query_vector, document_vectors[index])
                if query_vector is not None and index < len(document_vectors)
                else lexical
            )
            score = 0.75 * dense + 0.25 * lexical
            enriched = dict(row)
            enriched["summary_retrieval_score"] = round(score, 6)
            enriched["retrieval_source"] = "file-filter+summary-vector" if query_vector else "file-filter+summary-lexical"
            enriched["retrieval_reason"] = (
                "O arquivo foi filtrado estruturalmente e o resumo/objetivo foi reordenado "
                "por similaridade semântica."
            )
            scored.append(enriched)
        scored.sort(key=lambda row: (row["summary_retrieval_score"], int(row.get("pr_number", 0))), reverse=True)
        return scored[:limit]

    @staticmethod
    def _summary_text(row: dict) -> str:
        return " ".join(
            str(row.get(field, "")).strip()
            for field in ("summary", "objective")
            if str(row.get(field, "")).strip()
        )

    @staticmethod
    def _terms(text: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[\wÀ-ÿ]{3,}", text.casefold())
            if token not in {"para", "com", "que", "uma", "the", "and", "from", "this", "that"}
        }

    @staticmethod
    def _lexical_overlap(query_terms: set[str], document_terms: set[str]) -> float:
        if not query_terms:
            return 0.0
        return len(query_terms & document_terms) / len(query_terms)

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        dot = sum(a * b for a, b in zip(left, right, strict=True))
        norm_left = math.sqrt(sum(value * value for value in left))
        norm_right = math.sqrt(sum(value * value for value in right))
        return dot / (norm_left * norm_right) if norm_left and norm_right else 0.0
