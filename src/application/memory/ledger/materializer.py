from __future__ import annotations

from decisionssearch.domain.memory_ledger import OutboxStatus, RevisionState
from decisionssearch.domain.memory_ledger.models import utc_now


class QdrantHeadMaterializer:
    """Consumidor idempotente do outbox; Qdrant nunca decide identidade."""

    def __init__(self, ledger, qdrant, embeddings) -> None:  # noqa: ANN001
        self.ledger = ledger
        self.qdrant = qdrant
        self.embeddings = embeddings

    async def run_once(self, limit: int = 50) -> dict[str, int]:
        pending = await self.ledger.list_outbox()
        retryable = await self.ledger.list_outbox(status=OutboxStatus.FAILED)
        processing = await self.ledger.list_outbox(status=OutboxStatus.PROCESSING)
        events = sorted(
            {event.event_id: event for event in [*pending, *retryable, *processing]}.values(),
            key=lambda event: (event.sequence, event.created_at, str(event.event_id)),
        )[:limit]
        applied = 0
        failed_count = 0
        for event in events:
            try:
                worker_id = "qdrant-materializer"
                claim_token = None
                claim = getattr(self.ledger, "claim_outbox", None)
                if claim is not None:
                    claimed = await claim(event.event_id, worker_id=worker_id)
                    if claimed is None:
                        continue
                    event = claimed
                    claim_token = event.claim_token
                if event.event_type == "memory.relation.applied":
                    # Relações são projeções do grafo; Qdrant materializa apenas
                    # heads de revisão. Reprocessar uma aresta como se fosse uma
                    # revisão poderia apagar ou reindexar um head por engano.
                    await self.ledger.mark_outbox(
                        event.event_id,
                        OutboxStatus.APPLIED,
                        worker_id=worker_id if claim is not None else None,
                        claim_token=claim_token,
                    )
                    applied += 1
                    continue
                scope = dict(event.payload).get("scope", "semantic")
                branch = dict(event.payload).get("branch", "semantic")
                effective_rows = await self.ledger.list_effective_revisions(
                    memory_scope=scope,
                    memory_branch=branch,
                )
                revision = next(
                    (item for item in effective_rows if item.family_id == event.family_id),
                    None,
                )
                if revision is None:
                    await self._delete_head(
                        event.family_id, scope, branch, event.revision_id, event.sequence
                    )
                else:
                    view = await self.ledger.get_view(revision.revision_id)
                    if (
                        view.state is RevisionState.ACTIVE
                        and (
                            revision.content.valid_from is None
                            or revision.content.valid_from <= utc_now()
                        )
                        and (
                            revision.content.valid_to is None
                            or revision.content.valid_to > utc_now()
                        )
                    ):
                        text = f"{revision.content.title}\n{revision.content.summary}\n{revision.content.details}"
                        embedding = await self.embeddings.embed(text)
                        await self.qdrant.upsert_revision_head(
                            revision,
                            embedding,
                            ledger_sequence=event.sequence,
                        )
                    else:
                        await self._delete_head(
                            event.family_id, scope, branch, revision.revision_id, event.sequence
                        )
                await self.ledger.mark_outbox(
                    event.event_id,
                    OutboxStatus.APPLIED,
                    worker_id=worker_id if claim is not None else None,
                    claim_token=claim_token,
                )
                applied += 1
            except Exception as error:  # pragma: no cover - falha é exercitada com fake
                try:
                    await self.ledger.mark_outbox(
                        event.event_id,
                        OutboxStatus.FAILED,
                        str(error),
                        worker_id=worker_id if claim is not None else None,
                        claim_token=claim_token,
                    )
                except Exception:
                    # Um lease expirado/fenced deve deixar o evento para outro
                    # worker; não mascaramos a falha original.
                    pass
                failed_count += 1
        return {"seen": len(events), "applied": applied, "failed": failed_count}

    async def _delete_head(
        self,
        family_id,
        scope: str,
        branch: str,
        revision_id,
        ledger_sequence: int | None = None,
    ) -> None:  # noqa: ANN001
        delete = getattr(self.qdrant, "delete_revision_head", None)
        if delete is None:
            return
        try:
            await delete(
                revision_id,
                family_id=str(family_id),
                memory_scope=scope,
                memory_branch=branch,
                ledger_sequence=ledger_sequence,
            )
        except TypeError:
            # Compatibilidade com materializadores externos ainda baseados no
            # contrato antigo (somente revision_id).
            await delete(str(revision_id or family_id))

    async def rebuild(self) -> dict[str, int]:
        revisions = await self.ledger.list_active_revisions()
        if hasattr(self.qdrant, "ensure_collection"):
            await self.qdrant.ensure_collection()
        indexed = 0
        expected_point_ids: set[str] = set()
        for revision in revisions:
            text = f"{revision.content.title}\n{revision.content.summary}\n{revision.content.details}"
            embedding = await self.embeddings.embed(text)
            head = await self.ledger.get_head(
                revision.family_id,
                revision.content.memory_scope,
                revision.content.memory_branch,
            )
            await self.qdrant.upsert_revision_head(
                revision,
                embedding,
                # O rebuild precisa usar a sequência global do head, não a
                # versão local da família; caso contrário, um rebuild pode
                # parecer um evento atrasado para a projeção.
                ledger_sequence=head.sequence if head is not None else revision.version,
            )
            head_point_id = getattr(self.qdrant, "head_point_id", None)
            if head_point_id is not None:
                expected_point_ids.add(
                    head_point_id(
                        str(revision.family_id),
                        revision.content.memory_scope,
                        revision.content.memory_branch,
                    )
                )
            indexed += 1
        orphaned_removed = 0
        reconcile = getattr(self.qdrant, "delete_orphaned_heads", None)
        if reconcile is not None:
            orphaned_removed = await reconcile(expected_point_ids)
        return {
            "active_revisions": len(revisions),
            "indexed": indexed,
            "orphaned_removed": orphaned_removed,
        }
