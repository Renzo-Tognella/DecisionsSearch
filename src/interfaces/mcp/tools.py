from __future__ import annotations

import asyncio
import functools
import logging
import time
import uuid

from decisionssearch.domain import (
    CreateCategoryCommand,
    CreateDomainCommand,
    CreateManualMemoryCommand,
    CreatePRMemoryCommand,
    CreateProjectCommand,
    CreateRelationCommand,
    DeleteRelationCommand,
    UpdateCategoryCommand,
    UpdateDomainCommand,
    UpdateProjectCommand,
)
from decisionssearch.domain.episodic.episodic_memory import EpisodeStatus, EpisodicMemory
from decisionssearch.domain.shared.exceptions import MemoryServiceError, SanitizationError
from decisionssearch.domain.memory.memory_candidate import EvidenceRef, MemoryCandidate
from decisionssearch.domain.memory.memory_item import MemoryItem
from decisionssearch.domain.procedural.procedural_memory import ProceduralMemory
from decisionssearch.domain.memory.raw_event import RawEvent
from decisionssearch.domain.incidents.error_event import ErrorEvent
from decisionssearch.application.memory.commit_memory_hook import (
    CommitContext,
    PostCommitMemoryContext,
    PullRequestContext,
)
from decisionssearch.application.memory.ledger.services import ProposalService
from decisionssearch.application.memory.ledger.operator_identity import TrustedOperatorResolver
from decisionssearch.application.memory.ledger.views import revision_to_legacy_view
from decisionssearch.application.memory.project_context import resolve_project
from decisionssearch.domain.memory_ledger import LedgerOperation, MemoryContent, Evidence
from decisionssearch.bootstrap.container import ServiceContainer
from decisionssearch.interfaces.mcp.mcp_compat import FastMCP

logger = logging.getLogger(__name__)

TOOL_TIMEOUT_SECONDS = 120

# Versão da superfície de tools (G9). Clientes leem via resource
# meta://tools/version para detectar mudanças de schema.
TOOL_SURFACE_VERSION = "2.2"

VALID_MEMORY_RELATIONS = {
    "RELATED_TO",
    "DEPENDS_ON",
    "REFINES",
    "DEPRECATES",
    "CONFLICTS_WITH",
    "EVOLVES_FROM",
}


def _as_error(error: Exception) -> dict:
    error_type = type(error).__name__
    context = getattr(error, "context", None)
    logger.error("Tool error [%s]: %s", error_type, error, exc_info=True)
    result: dict = {"error": str(error), "type": error_type}
    if context:
        result["context"] = context
    return result


def _json_ready(value):  # noqa: ANN202
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _ledger_enabled(container) -> bool:  # noqa: ANN001
    """Detecta o gateway real sem ativar MagicMock dos testes de superfície."""

    return isinstance(getattr(container, "proposal_service", None), ProposalService)


def _resolve_memory_project(project: str | None = None) -> str:
    """Resolve the mandatory memory partition for an agent tool call."""

    return resolve_project(project)


def deprecated_tool(new_tool: str):  # noqa: ANN201
    """Marca uma tool como deprecated (C12) sem quebrá-la.

    Loga warning e injeta metadados de migração no retorno (quando dict),
    mantendo a tool funcional — migration shim. functools.wraps preserva a
    assinatura, então o schema MCP fica intacto. Aplicar ABAIXO de @app.tool::

        @app.tool(name="memory.upsert")
        @deprecated_tool("memory.create_sync")
        async def memory_upsert(...): ...
    """

    def wrap(fn):
        @functools.wraps(fn)
        async def inner(*a, **k):
            logger.warning(
                "Tool '%s' está deprecated; migre para '%s'.",
                getattr(fn, "__name__", "?"),
                new_tool,
            )
            result = await fn(*a, **k)
            if isinstance(result, dict):
                result.setdefault("_deprecated", True)
                result.setdefault("_migration", f"Use {new_tool} instead")
            return result

        return inner

    return wrap


def _instrument_tools(app: FastMCP, telemetry) -> None:
    """Faz cada @app.tool gravar telemetria (latência, tamanho, erro) — G7.

    functools.wraps preserva a assinatura, então FastMCP (que segue __wrapped__)
    mantém o schema MCP de cada tool intacto. Aplicado uma vez antes das 42
    definições, instrumenta todas sem editar cada uma.
    """
    from decisionssearch.application.governance.tool_telemetry_service import result_size as _result_size

    original = app.tool

    def traced_tool(*d_args, name=None, **d_kwargs):
        register = original(*d_args, name=name, **d_kwargs)

        def decorator(fn):
            tool_name = name or getattr(fn, "__name__", "unknown")

            @functools.wraps(fn)
            async def wrapper(*a, **k):
                start = time.perf_counter()
                err: str | None = None
                result = None
                try:
                    result = await fn(*a, **k)
                    return result
                except Exception as exc:
                    err = type(exc).__name__
                    raise
                finally:
                    telemetry.record_tool_call(
                        tool_name=tool_name,
                        args_hash=telemetry.hash_args({"a": list(a), "k": k}),
                        latency_ms=(time.perf_counter() - start) * 1000.0,
                        result_size=_result_size(result),
                        error=err,
                    )

            return register(wrapper)

        return decorator

    app.tool = traced_tool


def register_tools(app: FastMCP, c: ServiceContainer) -> None:
    if getattr(c, "tool_telemetry", None) is not None:
        _instrument_tools(app, c.tool_telemetry)

    @app.tool(name="memory.change.propose")
    async def memory_change_propose(
        category: str,
        title: str,
        summary: str,
        project: str | None = None,
        details: str = "",
        reason: str = "Alteração proposta pelo agente",
        source_kind: str = "agent_context",
        source_locator: str = "",
    ) -> dict:
        """Cria um preview server-side; não grava uma memória ativa."""
        if not _ledger_enabled(c):
            return {"error": "Versioned memory ledger is not configured"}
        try:
            project = _resolve_memory_project(project)
            content = MemoryContent(
                project=project,
                category=category,
                title=title,
                summary=summary,
                details=details,
            )
            evidence = Evidence(
                source_kind=source_kind,
                source_locator=source_locator or "agent_context",
            )
            proposal = await c.proposal_service.propose_create(
                content,
                requested_by="agent",
                evidence=(evidence,),
                reason=reason,
            )
            return {
                "proposal_id": str(proposal.proposal_id),
                "status": proposal.status.value,
                "requires_human_approval": True,
                "preview_hash": proposal.preview_hash,
                "before": [item.model_dump(mode="json") for item in proposal.before],
                "after": proposal.after.model_dump(mode="json") if proposal.after else None,
                "field_diff": [item.model_dump(mode="json") for item in proposal.field_diff],
                "evidence": [item.model_dump(mode="json") for item in proposal.evidence],
                "question": "A alteração faz sentido e deve ser aprovada?",
            }
        except Exception as error:
            return _as_error(error)

    @app.tool(name="memory.change.get")
    async def memory_change_get(proposal_id: str) -> dict:
        """Obtém exatamente o preview que será aprovado."""
        if not _ledger_enabled(c):
            return {"error": "Versioned memory ledger is not configured"}
        try:
            proposal = await c.ledger.get_proposal(uuid.UUID(proposal_id))
            return _json_ready(proposal)
        except Exception as error:
            return _as_error(error)

    @app.tool(name="memory.change.rollback")
    async def memory_change_rollback(
        family_id: str,
        restore_revision_id: str,
        expected_revision_id: str,
        reason: str,
    ) -> dict:
        """Cria proposta de rollback; nunca reativa a revisão histórica diretamente."""
        if not _ledger_enabled(c):
            return {"error": "Versioned memory ledger is not configured"}
        try:
            family = uuid.UUID(family_id)
            expected = uuid.UUID(expected_revision_id)
            proposal = await c.proposal_service.propose_rollback(
                family,
                uuid.UUID(restore_revision_id),
                (family, "semantic", "semantic", expected),
                reason=reason,
            )
            return _json_ready(proposal)
        except Exception as error:
            return _as_error(error)


    @app.tool(name="memory.pr.create")
    async def memory_pr_create(
        repo: str,
        pr_number: int,
        title: str,
        summary: str,
        changed_files: list[str],
        pr_url: str,
        work_item_url: str,
        project: str | None = None,
        objective: str = "",
        branch: str = "",
        work_item_id: str = "",
        work_item_summary: str = "",
        work_item_provider: str = "",
        areas: list[str] | None = None,
        authors: list[str] | None = None,
        status: str = "open",
        merged_at: str = "",
        event_date: str = "",
    ) -> dict:
        """Cria memória a partir de um Pull Request (PR + work item linkados).

        Use when: persistir o que um PR mudou e por quê; ligar PR a work item. Do NOT
        use for: regra/decisão genérica (memory.upsert); evento sem PR
        (memory.episode.create). pr_url e work_item_url são obrigatórios.
        Example: memory.pr.create(project='DecisionsSearch', repo='org/repo', pr_number=42,
        title='Add HyDE', summary='...', changed_files=[...], pr_url='...', work_item_url='...').
        """
        try:
            project = _resolve_memory_project(project)
            command = CreatePRMemoryCommand(
                project=project,
                repo=repo,
                pr_number=pr_number,
                title=title,
                summary=summary,
                objective=objective,
                changed_files=changed_files,
                pr_url=pr_url,
                branch=branch,
                work_item_id=work_item_id,
                work_item_url=work_item_url,
                work_item_summary=work_item_summary,
                work_item_provider=work_item_provider,
                areas=areas or [],
                authors=authors or [],
                status=status,
                merged_at=merged_at,
                event_date=event_date,
            )
            return _json_ready(await c.pr_memory.create_pr_memory(command))
        except Exception as error:
            return _as_error(error)

    @app.tool(name="memory.pr.query")
    async def memory_pr_query(
        project: str | None = None,
        repo: str = "",
        pr_number: int | None = None,
        changed_file_contains: str = "",
        summary_query: str = "",
        limit: int = 50,
    ) -> list[dict] | dict:
        """Consulta memórias de PR por projeto, repo ou arquivo alterado."""
        try:
            project = _resolve_memory_project(project)
            query_kwargs = {
                "project": project,
                "repo": repo or None,
                "pr_number": pr_number,
                "changed_file_contains": changed_file_contains or None,
            }
            if summary_query:
                query_kwargs["summary_query"] = summary_query
            if limit != 50:
                query_kwargs["limit"] = limit
            return _json_ready(
                await c.pr_memory.query_pr_memories(**query_kwargs)
            )
        except Exception as error:
            return _as_error(error)

    @app.tool(name="memory.pr.link_memory")
    async def memory_pr_link_memory(
        pr_memory_id: str,
        memory_id: str,
        relation_type: str = "IMPLEMENTS",
        rationale: str = "",
    ) -> dict:
        """Liga um PRMemory a um MemoryItem (IMPLEMENTS, EVIDENCES, MODIFIES)."""
        try:
            return _json_ready(
                await c.pr_memory.link_pr_to_memory(
                    pr_memory_id=pr_memory_id,
                    memory_id=memory_id,
                    relation_type=relation_type,
                    rationale=rationale,
                )
            )
        except Exception as error:
            return _as_error(error)

    @app.tool(name="memory.pr.linked_memories")
    async def memory_pr_linked_memories(pr_memory_id: str) -> list[dict] | dict:
        """Lista MemoryItems linkados a um PR."""
        try:
            return _json_ready(await c.pr_memory.query_pr_linked_memories(pr_memory_id))
        except Exception as error:
            return _as_error(error)

    @app.tool(name="memory.linked_prs")
    async def memory_linked_prs(memory_id: str) -> list[dict] | dict:
        """Lista PRs linkados a um MemoryItem."""
        try:
            return _json_ready(await c.pr_memory.query_memory_linked_prs(memory_id))
        except Exception as error:
            return _as_error(error)

    @app.tool(name="graph.catalog.export_csv")
    async def graph_catalog_export_csv() -> dict:
        """Exporta catálogo do grafo como bundle CSV."""
        try:
            return _json_ready(await c.catalog_csv.export_catalog_csv_bundle())
        except Exception as error:
            return _as_error(error)

    @app.tool(name="graph.catalog.import_csv")
    async def graph_catalog_import_csv(
        schema_version: str,
        projects_csv: str = "",
        categories_csv: str = "",
        domains_csv: str = "",
        relations_csv: str = "",
    ) -> dict:
        """Importa catálogo do grafo a partir de bundle CSV."""
        try:
            return _json_ready(
                await c.catalog_csv.import_catalog_csv_bundle(
                    {
                        "schema_version": schema_version,
                        "projects_csv": projects_csv,
                        "categories_csv": categories_csv,
                        "domains_csv": domains_csv,
                        "relations_csv": relations_csv,
                    }
                )
            )
        except Exception as error:
            return _as_error(error)

    @app.tool(name="graph.project.create")
    async def graph_project_create(
        slug: str,
        name: str,
        description: str = "",
        status: str = "active",
        aliases: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Cria um novo projeto no catálogo do grafo."""
        try:
            command = CreateProjectCommand(
                slug=slug,
                name=name,
                description=description,
                status=status,
                aliases=aliases or [],
                tags=tags or [],
            )
            return _json_ready(await c.graph_catalog.create_project(command))
        except Exception as error:
            return _as_error(error)

    @app.tool(name="graph.project.update")
    async def graph_project_update(
        id: str,
        slug: str,
        name: str,
        description: str = "",
        status: str = "active",
        aliases: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Atualiza dados de um projeto existente no catálogo."""
        try:
            command = UpdateProjectCommand(
                id=id,
                slug=slug,
                name=name,
                description=description,
                status=status,
                aliases=aliases or [],
                tags=tags or [],
            )
            return _json_ready(await c.graph_catalog.update_project(command))
        except Exception as error:
            return _as_error(error)

    @app.tool(name="graph.project.list")
    async def graph_project_list() -> list[dict] | dict:
        """Lista todos os projetos do catálogo."""
        try:
            return _json_ready(await c.graph_catalog.list_projects())
        except Exception as error:
            return _as_error(error)

    @app.tool(name="graph.category.create")
    async def graph_category_create(
        slug: str,
        name: str,
        project_id: str,
        description: str = "",
        status: str = "active",
        aliases: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Cria uma nova categoria no catálogo do grafo."""
        try:
            command = CreateCategoryCommand(
                slug=slug,
                name=name,
                project_id=project_id,
                description=description,
                status=status,
                aliases=aliases or [],
                tags=tags or [],
            )
            return _json_ready(await c.graph_catalog.create_category(command))
        except Exception as error:
            return _as_error(error)

    @app.tool(name="graph.category.update")
    async def graph_category_update(
        id: str,
        slug: str,
        name: str,
        project_id: str,
        description: str = "",
        status: str = "active",
        aliases: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Atualiza dados de uma categoria existente no catálogo."""
        try:
            command = UpdateCategoryCommand(
                id=id,
                slug=slug,
                name=name,
                project_id=project_id,
                description=description,
                status=status,
                aliases=aliases or [],
                tags=tags or [],
            )
            return _json_ready(await c.graph_catalog.update_category(command))
        except Exception as error:
            return _as_error(error)

    @app.tool(name="graph.domain.create")
    async def graph_domain_create(
        slug: str,
        name: str,
        project_id: str,
        description: str = "",
        status: str = "active",
        aliases: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Cria um novo domínio no catálogo do grafo."""
        try:
            command = CreateDomainCommand(
                slug=slug,
                name=name,
                project_id=project_id,
                description=description,
                status=status,
                aliases=aliases or [],
                tags=tags or [],
            )
            return _json_ready(await c.graph_catalog.create_domain(command))
        except Exception as error:
            return _as_error(error)

    @app.tool(name="graph.domain.update")
    async def graph_domain_update(
        id: str,
        slug: str,
        name: str,
        project_id: str,
        description: str = "",
        status: str = "active",
        aliases: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Atualiza dados de um domínio existente no catálogo."""
        try:
            command = UpdateDomainCommand(
                id=id,
                slug=slug,
                name=name,
                project_id=project_id,
                description=description,
                status=status,
                aliases=aliases or [],
                tags=tags or [],
            )
            return _json_ready(await c.graph_catalog.update_domain(command))
        except Exception as error:
            return _as_error(error)

    @app.tool(name="graph.relation.create")
    async def graph_relation_create(
        source_id: str,
        source_kind: str,
        relation_type: str,
        target_id: str,
        target_kind: str,
        rationale: str = "",
    ) -> dict:
        """Cria relação entre dois nós do catálogo do grafo."""
        try:
            command = CreateRelationCommand(
                source_id=source_id,
                source_kind=source_kind,
                relation_type=relation_type,
                target_id=target_id,
                target_kind=target_kind,
                rationale=rationale,
            )
            await c.graph_operations.create_relation(command)
            return {"status": "linked"}
        except Exception as error:
            return _as_error(error)

    @app.tool(name="graph.relation.delete")
    async def graph_relation_delete(
        source_id: str,
        source_kind: str,
        relation_type: str,
        target_id: str,
        target_kind: str,
    ) -> dict:
        """Remove relação entre dois nós do catálogo do grafo."""
        try:
            command = DeleteRelationCommand(
                source_id=source_id,
                source_kind=source_kind,
                relation_type=relation_type,
                target_id=target_id,
                target_kind=target_kind,
            )
            await c.graph_operations.delete_relation(command)
            return {"status": "deleted"}
        except Exception as error:
            return _as_error(error)

    @app.tool(name="memory.manual.create")
    async def memory_manual_create(
        category: str,
        title: str,
        summary: str,
        project: str | None = None,
        details: str = "",
        domain: list[str] | None = None,
        modules: list[str] | None = None,
        objective: str = "",
        trigger: str = "",
        stakeholders: list[str] | None = None,
        action_triggers: list[str] | None = None,
        related_files: list[str] | None = None,
        business_rules: list[str] | None = None,
        architectural_rationale: str = "",
        examples: list[str] | None = None,
        alternatives_considered: list[str] | None = None,
        event_date: str = "",
    ) -> dict:
        """Cria memória estruturada com categoria explícita (DesignRule, BusinessRule,
        ArchitecturalDecision, DesignPattern).

        Use when: o usuário dá uma regra/decisão/padrão já classificável e você sabe a
        categoria. Do NOT use for: salvar rápido sem categoria (memory.upsert); PR
        (memory.pr.create); passo-a-passo (memory.procedure.create); evento
        (memory.episode.create). ArchitecturalDecision exige alternatives_considered.
        Example: memory.manual.create(project='ExampleProject', category='DesignRule',
        title='Cache key', summary='pj:cache:{tenant}:{entity}'). Omit project to
        derive it from the agent workspace folder.
        """
        try:
            project = _resolve_memory_project(project)
            command = CreateManualMemoryCommand(
                project=project,
                category=category,
                domain=domain or [],
                modules=modules or [],
                title=title,
                summary=summary,
                details=details,
                objective=objective,
                trigger=trigger,
                stakeholders=stakeholders or [],
                action_triggers=action_triggers or [],
                related_files=related_files or [],
                business_rules=business_rules or [],
                architectural_rationale=architectural_rationale,
                examples=examples or [],
                alternatives_considered=alternatives_considered or [],
                event_date=event_date,
            )
            return _json_ready(await c.manual_memory_authoring.create_manual_memory(command))
        except Exception as error:
            return _as_error(error)

    @app.tool(name="memory.query")
    async def memory_query(
        project: str | None = None,
        type: str | None = None,
        query_text: str | None = None,
        top_k: int = 10,
        min_weight: float = 0.0,
        hyde: bool = False,
        memory_scope: str = "semantic",
        memory_branch: str | None = None,
    ) -> list[dict] | dict:
        """Busca semântica + grafo de memórias de um projeto (o jeito padrão de RECUPERAR).

        Use when: responder "como/por que/qual" sobre um projeto; recuperar regras,
        decisões e padrões. Do NOT use for: pegar 1 memória por id (memory.get); ponto
        no tempo (memory.query_at); montar pacote de contexto pra uma task
        (memory.context). hyde=True força expansão HyDE (queries curtas/vagas; +1 LLM call).
        Omit project to query only the project resolved from the agent workspace folder.
        """
        try:
            project = _resolve_memory_project(project)
            results = await c.search.search(
                query_text=query_text,
                project=project,
                category=type,
                top_k=top_k,
                min_weight=min_weight,
                use_hyde=hyde,
                memory_scope=memory_scope,
                memory_branch=memory_branch,
            )
            for item in results:
                memory_id = item.get("memory_id")
                if memory_id:
                    c.telemetry.record_retrieval(memory_id)
            return results
        except MemoryServiceError as error:
            return _as_error(error)

    @app.tool(name="memory.find_duplicates")
    async def memory_find_duplicates(
        text: str,
        project: str | None = None,
        type: str | None = None,
        threshold: float = 0.85,
        memory_scope: str = "semantic",
        memory_branch: str | None = None,
    ) -> list[dict] | dict:
        """Lista memórias similares (>= threshold). Chame ANTES de criar p/ evitar duplicatas.

        text = título + summary da memória que você pretende criar. Use o resultado para
        decidir entre criar nova (memory.upsert/memory.manual.create) ou refinar uma
        existente (search-before-write, S3). Default 0.85 calibrado para o MiniLM local
        (cosine fica ~0.86 em quase-idênticos); suba para ~0.92 com embeddings maiores.
        Omit project to use the agent workspace folder.
        """
        try:
            project = _resolve_memory_project(project)
            embedding = await c.embeddings.embed(text)
            return await c.qdrant.find_similar(
                embedding=embedding,
                project=project,
                type=type or "",
                threshold=threshold,
                memory_scope=memory_scope,
                memory_branch=memory_branch,
            )
        except MemoryServiceError as error:
            return _as_error(error)

    @app.tool(name="memory.get")
    async def memory_get(memory_id: str) -> dict:
        """Recupera UMA memória pelo memory_id exato (lookup direto, sem busca).

        Use when: você já tem o memory_id (veio de memory.query/find_duplicates) e quer
        o registro completo. Do NOT use for: busca por tema (memory.query).
        Example: memory.get(memory_id='c3f814b1babebd35').
        """
        try:
            if _ledger_enabled(c):
                alias = await c.ledger.resolve_alias(memory_id)
                if alias is not None and alias.status.value == "ambiguous":
                    return {
                        "error": "Memory alias is ambiguous",
                        "memory_id": memory_id,
                        "candidates": [str(item) for item in alias.candidates],
                    }
                if alias is None or alias.family_id is None:
                    return {"error": "Memory alias not found", "memory_id": memory_id}
                family = await c.ledger.get_family(alias.family_id)
                head = await c.ledger.get_head(
                    alias.family_id,
                    family.memory_scope if family else "semantic",
                    alias.memory_branch,
                )
                if head is None:
                    return {"error": "Memory family has no current head", "memory_id": memory_id}
                revision = await c.ledger.get_revision(head.revision_id)
                if revision is None:
                    return {"error": "Memory revision not found", "memory_id": memory_id}
                view = await c.ledger.get_view(revision.revision_id)
                family = await c.ledger.get_family(revision.family_id)
                return revision_to_legacy_view(
                    revision,
                    view.state,
                    family.legacy_memory_id if family else "",
                )
            mem = await c.neo4j.get_memory(memory_id)
            if mem is None:
                return {"error": "Memory not found", "memory_id": memory_id}
            return mem
        except MemoryServiceError as error:
            return _as_error(error)

    @app.tool(name="memory.query_at")
    async def memory_query_at(
        point_in_time: str,
        project: str | None = None,
        category: str | None = None,
        limit: int = 20,
        memory_scope: str | None = None,
        memory_branch: str | None = None,
    ) -> list[dict] | dict:
        """Consulta memórias que estavam ATIVAS num instante passado (bitemporal, ISO 8601).

        Use when: auditoria / "o que valia em <data>"; reconstruir estado histórico.
        Do NOT use for: estado atual (memory.query).
        Example: memory.query_at(project='CORE', point_in_time='2026-01-01T00:00:00Z').
        """
        try:
            project = _resolve_memory_project(project)
            from datetime import datetime

            dt = datetime.fromisoformat(point_in_time.replace("Z", "+00:00"))
            if _ledger_enabled(c):
                revisions = await c.ledger.list_effective_revisions(
                    project=project,
                    category=category,
                    memory_scope=memory_scope,
                    memory_branch=memory_branch,
                    valid_at=dt,
                    recorded_at=dt,
                )
                historical_rows = []
                for revision in revisions:
                    family = await c.ledger.get_family(revision.family_id)
                    historical_rows.append(
                        revision_to_legacy_view(
                            revision,
                            memory_id=family.legacy_memory_id if family else "",
                        )
                    )
                return historical_rows[:limit]
            results = await c.neo4j.query_at_point_in_time(
                project=project,
                point_in_time=dt,
                category=category,
                limit=limit,
            )
            return results
        except (MemoryServiceError, ValueError) as error:
            return _as_error(error)

    @app.tool(name="memory.upsert")
    async def memory_upsert(
        category: str,
        title: str,
        summary: str,
        project: str | None = None,
        details: str = "",
        domain: list[str] | None = None,
        weight_manual: float = 0.5,
    ) -> dict:
        """Cria/atualiza memória canônica de forma idempotente (o jeito padrão de SALVAR).

        Use when: persistir rápido uma regra/decisão/fato técnico; o admission decide
        create vs refine. Do NOT use for: PR (memory.pr.create); passo-a-passo
        (memory.procedure.create); evento único (memory.episode.create); texto cru pra
        extração (memory.ingest_raw). Chame memory.find_duplicates ANTES p/ evitar
        duplicata. Example: memory.upsert(project='ExampleProject', category='DesignRule',
        title='Cache key', summary='pj:cache:{tenant}:{entity}'). Omit project to
        derive it from the agent workspace folder.
        """
        try:
            project = _resolve_memory_project(project)
            candidate = MemoryCandidate(
                project=project,
                type=category,
                domain=domain or [],
                title=title,
                summary=summary,
                details=details,
                proposed_weight=weight_manual,
                evidence=[EvidenceRef(type="manual", ref="direct_upsert", snippet="")],
            )
            admission = await c.admission.evaluate(candidate)
            if _ledger_enabled(c):
                proposal = await c.proposal_service.propose_candidate(
                    candidate,
                    admission,
                    requested_by="agent",
                    reason="memory.upsert requer aprovação explícita",
                )
                return {
                    "proposal_id": str(proposal.proposal_id),
                    "status": proposal.status.value,
                    "requires_human_approval": True,
                    "preview_hash": proposal.preview_hash,
                    "before": [item.model_dump(mode="json") for item in proposal.before],
                    "after": proposal.after.model_dump(mode="json") if proposal.after else None,
                    "field_diff": [item.model_dump(mode="json") for item in proposal.field_diff],
                    "evidence": [item.model_dump(mode="json") for item in proposal.evidence],
                    "question": "A alteração faz sentido e deve ser aprovada?",
                }
            item = await c.persistence.persist(candidate, admission)
            c.audit.log_memory_change(
                action="upsert",
                memory_id=item.memory_id,
                changes={"title": item.title, "category": item.category},
                rationale="Direct upsert via tool",
            )
            return {"memory_id": item.memory_id, "status": "upserted"}
        except MemoryServiceError as error:
            return _as_error(error)

    @app.tool(name="memory.ingest_raw")
    async def memory_ingest_raw(
        source_kind: str,
        payload: str,
        project_hint: str | None = None,
        domain_hint: str | None = None,
    ) -> dict:
        """Ingere texto CRU e deixa o pipeline extrair/classificar/persistir sozinho.

        Use when: você tem um blob não-estruturado (log, mensagem, doc) e quer que o
        sistema decida o que virar memória. Do NOT use for: conteúdo já estruturado que
        você sabe classificar (memory.upsert/memory.manual.create). Mais caro (LLM de
        extração). Example: memory.ingest_raw(source_kind='slack', payload='<texto>',
        project_hint='CORE'). Omit project_hint to derive the project from the agent
        workspace folder.
        """
        try:
            project_hint = _resolve_memory_project(project_hint)
            return await asyncio.wait_for(
                _ingest_raw_impl(c, source_kind, payload, project_hint, domain_hint),
                timeout=TOOL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.error("memory.ingest_raw timeout após %ss", TOOL_TIMEOUT_SECONDS)
            return _as_error(TimeoutError(f"ingest_raw excedeu {TOOL_TIMEOUT_SECONDS}s"))
        except (MemoryServiceError, SanitizationError, ValueError) as error:
            return _as_error(error)

    async def _ingest_raw_impl(
        c: ServiceContainer,
        source_kind: str,
        payload: str,
        project_hint: str | None,
        domain_hint: str | None,
    ) -> dict:
        c.sanitization.validate_payload_size(payload)
        sanitized_payload = c.sanitization.sanitize(payload)
        context = await c.resolver.resolve(
            text=sanitized_payload,
            project_hint=project_hint,
            domain_hint=domain_hint,
        )
        event = RawEvent(
            event_id=str(uuid.uuid4()),
            source_kind=source_kind,
            payload=sanitized_payload,
            project_hint=context.get("project"),
            domain_hint=(context.get("domain") or [None])[0],
            metadata={"probable_category": context.get("probable_category")},
        )
        c.landing_zone.append_raw_event(event)

        candidates = await c.extraction.extract_candidates(
            content=sanitized_payload,
            project=context.get("project") or project_hint or "CORE",
            probable_category=context.get("probable_category"),
            domain=context.get("domain") or [],
        )
        processed: list[dict] = []
        for candidate in candidates:
            admission_result = await c.admission.evaluate(candidate)
            if admission_result.status in ("active", "proposed"):
                item = await c.persistence.persist(candidate, admission_result)
                if isinstance(item, dict):
                    processed.append(
                        {
                            "title": candidate.title,
                            "memory_id": item.get("memory_id"),
                            "proposal_id": item.get("proposal_id"),
                            "status": "pending_approval",
                            "action": admission_result.action,
                            "requires_human_approval": True,
                        }
                    )
                    continue
                is_proposal = str(item.memory_id).startswith("proposal:")
                processed.append(
                    {
                        "title": item.title,
                        "memory_id": None if is_proposal else item.memory_id,
                        "proposal_id": str(item.memory_id).split(":", 1)[1] if is_proposal else None,
                        "status": "pending_approval" if is_proposal else admission_result.status,
                        "action": admission_result.action,
                    }
                )
                c.audit.log_memory_change(
                    action=admission_result.action,
                    memory_id=item.memory_id,
                    changes={"title": item.title, "category": item.category},
                    rationale=admission_result.reason,
                )
            else:
                processed.append(
                    {
                        "title": candidate.title,
                        "status": admission_result.status,
                        "action": admission_result.action,
                        "reason": admission_result.reason,
                    }
                )

        c.audit.log_tool_call(
            "memory_ingest_raw",
            {"source_kind": source_kind},
            {"status": "received", "event_id": event.event_id},
        )
        return {
            "event_id": event.event_id,
            "status": "received",
            "persisted": not any(item.get("proposal_id") for item in processed),
            "requires_human_approval": any(item.get("proposal_id") for item in processed),
            "context": context,
            "candidates_extracted": len(candidates),
            "results": processed,
        }

    @app.tool(name="memory.list_raw_events")
    async def memory_list_raw_events(limit: int = 20) -> list[dict] | dict:
        """Lista eventos da landing zone para inspeção."""
        try:
            events = c.landing_zone.read_raw_events(limit=limit)
            return [event.model_dump(mode="json") for event in events]
        except Exception as error:  # pragma: no cover
            return _as_error(error)

    @app.tool(name="memory.set_weight")
    async def memory_set_weight(memory_id: str, weight_manual: float, rationale: str) -> dict:
        """Define peso manual de uma memória e recalcula peso efetivo."""
        try:
            if _ledger_enabled(c):
                alias = await c.ledger.resolve_alias(memory_id)
                if alias is None or alias.family_id is None:
                    return {"error": "Memory alias not found", "memory_id": memory_id}
                family = await c.ledger.get_family(alias.family_id)
                head = await c.ledger.get_head(
                    alias.family_id,
                    family.memory_scope if family else "semantic",
                    alias.memory_branch,
                )
                if head is None:
                    return {"error": "Memory family has no current head", "memory_id": memory_id}
                revision = await c.ledger.get_revision(head.revision_id)
                if revision is None:
                    return {"error": "Memory revision not found", "memory_id": memory_id}
                updated_content = revision.content.model_copy(
                    update={"weight_manual": weight_manual}
                )
                proposal = await c.proposal_service.propose_update(
                    alias.family_id,
                    updated_content,
                    requested_by="agent",
                    reason=f"Atualização governada de peso manual para {weight_manual}: {rationale}",
                    idempotency_key=f"weight:{memory_id}:{weight_manual}:{revision.revision_id}",
                )
                return {
                    "memory_id": memory_id,
                    "status": proposal.status.value,
                    "proposal_id": str(proposal.proposal_id),
                    "preview_hash": proposal.preview_hash,
                    "requires_human_approval": True,
                    "weight_manual": weight_manual,
                    "question": "A alteração de peso faz sentido e deve ser aprovada?",
                }
            rows = await c.neo4j.query_by_project(project="*", status="active", limit=5000)
            existing = None
            for row in rows:
                mem = row.get("memory", {})
                if mem.get("memory_id") == memory_id:
                    existing = mem
                    break
            if not existing:
                return {"error": "Memory not found", "memory_id": memory_id}

            category = existing.get("category", "DesignPattern")
            category_config = c.weight.get_priority_config(category)
            weight_confidence = float(existing.get("weight_confidence", 0.5) or 0.5)
            weight_usage = float(existing.get("weight_usage", 0.0) or 0.0)
            weight_feedback = float(existing.get("weight_feedback", 0.0) or 0.0)
            effective_weight = max(
                0.0,
                min(
                    1.0,
                    round(
                        category_config.alpha * weight_manual
                        + category_config.beta * weight_confidence
                        + category_config.gamma * weight_usage
                        + category_config.delta * weight_feedback
                        + category_config.epsilon * 0.5,
                        4,
                    ),
                ),
            )
            await c.neo4j.set_weight(memory_id, weight_manual, effective_weight)
            c.audit.log_memory_change(
                action="weight_change",
                memory_id=memory_id,
                changes={"weight_manual": weight_manual, "effective_weight": effective_weight},
                rationale=rationale,
            )
            return {
                "memory_id": memory_id,
                "weight_manual": weight_manual,
                "effective_weight": effective_weight,
                "status": "updated",
            }
        except MemoryServiceError as error:
            return _as_error(error)

    @app.tool(name="memory.deprecate")
    async def memory_deprecate(
        memory_id: str,
        replaced_by: str | None = None,
        rationale: str = "",
    ) -> dict:
        """Depreca memória e opcionalmente liga DEPRECATES para substituta."""
        try:
            if _ledger_enabled(c):
                alias = await c.ledger.resolve_alias(memory_id)
                if alias is None or alias.family_id is None:
                    return {"error": "Memory alias not found", "memory_id": memory_id}
                replacement_family_id = None
                if replaced_by:
                    replacement = await c.ledger.resolve_alias(replaced_by)
                    if replacement is None or replacement.family_id is None:
                        return {
                            "error": "Replacement memory alias not found",
                            "memory_id": memory_id,
                            "replaced_by": replaced_by,
                            "status": "quarantined",
                        }
                    if replacement.family_id == alias.family_id:
                        return {
                            "error": "A memory cannot replace itself",
                            "memory_id": memory_id,
                            "replaced_by": replaced_by,
                        }
                    replacement_family_id = replacement.family_id
                proposal = await c.proposal_service.propose_state_change(
                    alias.family_id,
                    LedgerOperation.INVALIDATE,
                    requested_by="agent",
                    reason=rationale or "Invalidação proposta pelo agente",
                    memory_branch=alias.memory_branch,
                    replacement_family_id=replacement_family_id,
                    replacement_alias=replaced_by or "",
                )
                return {
                    "memory_id": memory_id,
                    "proposal_id": str(proposal.proposal_id),
                    "status": proposal.status.value,
                    "requires_human_approval": True,
                    "preview_hash": proposal.preview_hash,
                    "before": [item.model_dump(mode="json") for item in proposal.before],
                    "after": proposal.after.model_dump(mode="json") if proposal.after else None,
                    "question": "A invalidação faz sentido e deve ser aprovada?",
                    "replaced_by": replaced_by,
                }
            await c.neo4j.deprecate_memory(memory_id=memory_id, replaced_by=replaced_by)
            c.audit.log_memory_change(
                action="deprecate",
                memory_id=memory_id,
                changes={"replaced_by": replaced_by},
                rationale=rationale,
            )
            return {"memory_id": memory_id, "status": "deprecated", "replaced_by": replaced_by}
        except MemoryServiceError as error:
            return _as_error(error)

    @app.tool(name="memory.link")
    async def memory_link(from_id: str, rel: str, to_id: str) -> dict:
        """Cria relação semântica entre duas memórias."""
        if rel not in VALID_MEMORY_RELATIONS:
            return {
                "error": f"Invalid relation type: {rel}. Valid: {sorted(VALID_MEMORY_RELATIONS)}"
            }
        try:
            if _ledger_enabled(c):
                source = await c.ledger.resolve_alias(from_id)
                target = await c.ledger.resolve_alias(to_id)
                if not source or not source.family_id or not target or not target.family_id:
                    return {"error": "Both memory aliases must be resolved before proposing a relation"}
                proposal = await c.proposal_service.propose_link(
                    source.family_id,
                    target.family_id,
                    rel,
                    requested_by="agent",
                    idempotency_key=f"link:{from_id}:{to_id}:{rel}",
                )
                return {
                    "from": from_id,
                    "relation": rel,
                    "to": to_id,
                    "proposal_id": str(proposal.proposal_id),
                    "status": proposal.status.value,
                    "requires_human_approval": True,
                    "preview_hash": proposal.preview_hash,
                    "question": "A relação faz sentido e deve ser aprovada?",
                }
            await c.neo4j.link_memories(from_id=from_id, rel_type=rel, to_id=to_id)
            return {"from": from_id, "relation": rel, "to": to_id, "status": "linked"}
        except MemoryServiceError as error:
            return _as_error(error)

    @app.tool(name="memory.consolidate")
    async def memory_consolidate(scope: str = "all", mode: str = "deferred") -> dict:
        """Dispara consolidação imediata ou diferida."""
        try:
            if _ledger_enabled(c):
                proposals = await c.consolidation.propose_now(scope=scope)
                return {
                    "status": "proposals_created",
                    "requires_human_approval": True,
                    "message": "A consolidação gerou previews de merge; nenhuma memória foi alterada.",
                    "scope": scope,
                    "proposal_count": len(proposals),
                    "proposals": proposals,
                }
            if mode == "immediate":
                count = await asyncio.wait_for(
                    c.consolidation.run_now(scope=scope),
                    timeout=TOOL_TIMEOUT_SECONDS,
                )
                return {"status": "completed", "items_processed": count}
            job_id = await c.consolidation.schedule(scope=scope)
            return {"status": "scheduled", "job_id": job_id}
        except asyncio.TimeoutError:
            logger.error("memory.consolidate timeout após %ss", TOOL_TIMEOUT_SECONDS)
            return _as_error(TimeoutError(f"consolidate excedeu {TOOL_TIMEOUT_SECONDS}s"))
        except MemoryServiceError as error:
            return _as_error(error)

    @app.tool(name="memory.feedback")
    async def memory_feedback(memory_id: str, score: float, accepted: bool = True) -> dict:
        """Registra feedback de uso para telemetria."""
        c.telemetry.record_feedback(memory_id, score)
        if accepted:
            c.telemetry.record_acceptance(memory_id)
        else:
            c.telemetry.record_rejection(memory_id, reason="explicit_feedback")
        if _ledger_enabled(c):
            try:
                alias = await c.ledger.resolve_alias(memory_id)
                if alias is None or alias.family_id is None:
                    return {"memory_id": memory_id, "status": "recorded", "error": "Memory alias not found"}
                family = await c.ledger.get_family(alias.family_id)
                head = await c.ledger.get_head(alias.family_id, family.memory_scope, alias.memory_branch)
                revision = await c.ledger.get_revision(head.revision_id) if head else None
                if revision is None:
                    return {"memory_id": memory_id, "status": "recorded", "error": "Memory revision not found"}
                updated_content = revision.content.model_copy(
                    update={
                        "weight_feedback": c.weight.update_on_feedback(
                            revision.content.weight_feedback, score
                        ),
                        "weight_usage": c.weight.update_on_retrieval(
                            revision.content.weight_usage, accepted
                        ),
                    }
                )
                proposal = await c.proposal_service.propose_update(
                    alias.family_id,
                    updated_content,
                    requested_by="feedback",
                    reason="Feedback explícito recebido para a memória",
                    idempotency_key=f"feedback:{memory_id}:{revision.revision_id}:{score}:{accepted}",
                )
                return {
                    "memory_id": memory_id,
                    "status": "pending_approval",
                    "proposal_id": str(proposal.proposal_id),
                    "preview_hash": proposal.preview_hash,
                    "requires_human_approval": True,
                }
            except Exception as error:
                return {"memory_id": memory_id, "status": "recorded", "error": str(error)}
        return {"memory_id": memory_id, "status": "recorded"}

    @app.tool(name="memory.context")
    async def memory_context(project: str | None = None, domain: str | None = None) -> dict:
        """Monta um PACOTE de contexto (regras/padrões/decisões) ANTES de começar uma task.

        Use when: vai iniciar um trabalho num projeto/domínio e quer o conhecimento
        relevante pré-carregado de uma vez. Do NOT use for: responder 1 pergunta pontual
        (memory.query); destilar pós-task (memory.reflect).
        Example: memory.context(project='ExampleProject', domain='cache').
        """
        try:
            project = _resolve_memory_project(project)
            context = await c.agent_loop.pre_task_context(project=project, domain=domain)
            return c.sanitization.sanitize_output(context)
        except MemoryServiceError as error:
            return _as_error(error)

    @app.tool(name="memory.reconcile")
    async def memory_reconcile(project: str | None = None) -> dict:
        """Verifica consistência entre Neo4j e Qdrant e remove vetores órfãos."""
        try:
            return await asyncio.wait_for(
                c.consolidation.reconcile_stores(project=project),
                timeout=TOOL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.error("memory.reconcile timeout após %ss", TOOL_TIMEOUT_SECONDS)
            return _as_error(TimeoutError(f"reconcile excedeu {TOOL_TIMEOUT_SECONDS}s"))
        except MemoryServiceError as error:
            return _as_error(error)

    @app.tool(name="memory.reflect")
    async def memory_reflect(
        task_description: str,
        changes: str,
        project: str | None = None,
        outcome: str = "completed",
    ) -> dict:
        """Extrai conhecimento de uma task CONCLUÍDA e persiste (loop de pós-task).

        Use when: terminou um trabalho e quer destilar o que foi aprendido em memória
        durável. Do NOT use for: RECUPERAR conhecimento (memory.query); pré-task
        (memory.context). outcome: 'completed' | 'failed' | 'partial'.
        Example: memory.reflect(task_description='Implementei HyDE opt-in', changes='...',
        project='DecisionsSearch').
        """
        try:
            project = _resolve_memory_project(project)
            sanitized_desc = c.sanitization.sanitize(task_description)
            sanitized_changes = c.sanitization.sanitize(changes)
            result = await c.agent_loop.post_task_summary(
                task_description=sanitized_desc,
                changes=sanitized_changes,
                project=project,
                outcome=outcome,
            )
            return c.sanitization.sanitize_output(result)
        except MemoryServiceError as error:
            return _as_error(error)

    @app.tool(name="memory.capture_commit")
    async def memory_capture_commit(
        commit_sha: str,
        project: str | None = None,
        session_context: str = "",
        session_id: str = "",
        commit_subject: str = "",
        commit_body: str = "",
        commit_author: str = "",
        branch: str = "",
        repository: str = "",
        changed_files: list[str] | None = None,
        diff: str = "",
        pull_request_number: int | None = None,
        pull_request_title: str = "",
        pull_request_url: str = "",
        pull_request_body: str = "",
        pull_request_state: str = "",
        pull_request_head_branch: str = "",
        pull_request_base_branch: str = "",
        pull_request_changed_files: list[str] | None = None,
        dry_run: bool = False,
    ) -> dict:
        """Verifica memória durável a partir da sessão e do commit/PR atual.

        Use depois de concluir um commit ou PR quando houver contexto da sessão
        para explicar intenção e impacto. O LLM pode retornar ``no_memory``;
        essa resposta é correta e não cria candidato. O resultado ainda passa
        pelos gates de admissão e, em ``dry_run``, apenas mostra propostas.
        O hook nunca deve ser usado para bloquear o commit.
        """
        try:
            project = _resolve_memory_project(project)
            context = PostCommitMemoryContext(
                project=project,
                session_text=session_context,
                session_id=session_id,
                commit=CommitContext(
                    sha=commit_sha,
                    subject=commit_subject,
                    body=commit_body,
                    author=commit_author,
                    branch=branch,
                    repository=repository,
                    changed_files=tuple(changed_files or []),
                    diff=diff,
                ),
                pull_request=PullRequestContext(
                    number=pull_request_number,
                    repository=repository,
                    title=pull_request_title,
                    url=pull_request_url,
                    body=pull_request_body,
                    state=pull_request_state,
                    head_branch=pull_request_head_branch,
                    base_branch=pull_request_base_branch,
                    changed_files=tuple(pull_request_changed_files or []),
                ),
            )
            result = await asyncio.wait_for(
                c.commit_memory.capture(context, dry_run=dry_run),
                timeout=TOOL_TIMEOUT_SECONDS,
            )
            return c.sanitization.sanitize_output(result)
        except asyncio.TimeoutError:
            return _as_error(TimeoutError(f"capture_commit excedeu {TOOL_TIMEOUT_SECONDS}s"))
        except (MemoryServiceError, SanitizationError, ValueError) as error:
            return _as_error(error)

    @app.tool(name="memory.procedure.create")
    async def memory_procedure_create(
        task_type: str,
        steps: list[str],
        project: str | None = None,
        preconditions: list[str] | None = None,
        tools_required: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Cria um PROCEDIMENTO reutilizável (passo-a-passo) para um tipo de tarefa.

        Use when: o conhecimento é uma sequência de passos repetível (runbook, how-to).
        Do NOT use for: regra/fato estático (memory.upsert); registro de um evento único
        (memory.episode.create). Example: memory.procedure.create(project='CORE',
        task_type='deploy', steps=['build', 'migrate', 'rollout']).
        """
        try:
            project = _resolve_memory_project(project)
            proc = ProceduralMemory(
                procedure_id=MemoryItem.generate_id(project, "procedure", task_type),
                project=project,
                task_type=task_type,
                steps=steps,
                preconditions=preconditions or [],
                tools_required=tools_required or [],
                tags=tags or [],
            )
            return await c.procedural_memory.create_procedure(proc)
        except Exception as error:
            return _as_error(error)

    @app.tool(name="memory.procedure.query")
    async def memory_procedure_query(
        project: str | None = None,
        task_type: str | None = None,
        limit: int = 20,
    ) -> list[dict] | dict:
        """Consulta procedimentos armazenados por tipo de tarefa."""
        try:
            project = _resolve_memory_project(project)
            return await c.procedural_memory.query_procedures(
                project=project, task_type=task_type, limit=limit
            )
        except MemoryServiceError as error:
            return _as_error(error)

    @app.tool(name="memory.episode.create")
    async def memory_episode_create(
        task_description: str,
        project: str | None = None,
        approach: str = "",
        outcome: str = "completed",
        lessons: list[str] | None = None,
        related_memory_ids: list[str] | None = None,
        tags: list[str] | None = None,
        occurrence_id: str | None = None,
    ) -> dict:
        """Registra um EPISÓDIO: o que foi feito numa task específica e o resultado.

        Use when: capturar um acontecimento único (o que tentei, deu certo/errado, lições).
        Do NOT use for: conhecimento atemporal/regra (memory.upsert); passo-a-passo
        reutilizável (memory.procedure.create). Example: memory.episode.create(
        project='CORE', task_description='Migrei PLD', outcome='completed', lessons=['...']).
        """
        try:
            project = _resolve_memory_project(project)
            episode = EpisodicMemory(
                episode_id=occurrence_id or str(uuid.uuid4()),
                project=project,
                task_description=task_description,
                approach=approach,
                outcome=EpisodeStatus(outcome),
                lessons=lessons or [],
                related_memory_ids=related_memory_ids or [],
                tags=tags or [],
            )
            return await c.episodic_memory.create_episode(episode)
        except Exception as error:
            return _as_error(error)

    @app.tool(name="memory.episode.query")
    async def memory_episode_query(
        project: str | None = None,
        outcome: str | None = None,
        tag: str | None = None,
        limit: int = 20,
    ) -> list[dict] | dict:
        """Consulta memórias episódicas por projeto, outcome ou tag."""
        try:
            project = _resolve_memory_project(project)
            return await c.episodic_memory.query_episodes(
                project=project, outcome=outcome, tag=tag, limit=limit
            )
        except MemoryServiceError as error:
            return _as_error(error)

    # ── Error & Jobs tools ─────────────────────────────────────────

    @app.tool(name="errors.ingest")
    async def errors_ingest(
        error_type: str,
        error_message: str,
        stack_trace: str = "",
        service: str = "",
        environment: str = "",
    ) -> dict:
        """Ingesta um erro e dispara pipeline de investigação automaticamente."""
        orchestrator = getattr(c, "error_orchestrator", None)
        if not orchestrator:
            return {"error": "Error pipeline not configured"}
        event = ErrorEvent(
            error_type=error_type,
            error_message=error_message,
            stack_trace=stack_trace,
            service=service,
            environment=environment,
        )
        try:
            return await orchestrator.handle_error(event)
        except Exception as e:
            return _as_error(e)

    @app.tool(name="errors.list")
    async def errors_list(
        service: str = "",
        error_type: str = "",
        limit: int = 20,
    ) -> list[dict] | dict:
        """Lista erros ingeridos, opcionalmente filtrando por service ou error_type."""
        error_svc = getattr(c, "error_service", None)
        if not error_svc:
            return {"error": "Error service not configured"}
        try:
            return await error_svc.list_errors(service=service, error_type=error_type, limit=limit)
        except Exception as e:
            return _as_error(e)

    @app.tool(name="errors.get_investigation")
    async def errors_get_investigation(error_id: str) -> dict:
        """Recupera detalhes da investigação de um erro."""
        error_svc = getattr(c, "error_service", None)
        if not error_svc:
            return {"error": "Error service not configured"}
        try:
            return await error_svc.get_investigation(error_id)
        except Exception as e:
            return _as_error(e)

    @app.tool(name="system.jobs.list")
    async def system_jobs_list() -> list[dict] | dict:
        """Lista jobs agendados (consolidação, summary, etc.)."""
        sched = getattr(c, "scheduler", None)
        if not sched:
            return {"error": "Scheduler not configured"}
        return sched.list_jobs()

    @app.tool(name="system.jobs.run")
    async def system_jobs_run(job_name: str) -> dict:
        """Executa um job agendado imediatamente."""
        sched = getattr(c, "scheduler", None)
        if not sched:
            return {"error": "Scheduler not configured"}
        try:
            run = await sched.run_job_now(job_name)
            return run.model_dump(mode="json")
        except Exception as e:
            return _as_error(e)

    @app.tool(name="system.jobs.history")
    async def system_jobs_history(job_name: str, limit: int = 20) -> list[dict]:
        """Historico de execucoes de um job."""
        sched = getattr(c, "scheduler", None)
        if not sched:
            return []
        return sched.get_job_history(job_name, limit=limit)

    @app.tool(name="system.scan.full")
    async def system_scan_full() -> dict:
        """Full scan of all PRs from configured GitHub repos + Shortcut cards. Imports everything, not just recent."""
        scanner = getattr(c, "daily_scan", None)
        if not scanner:
            return {"error": "Daily scan not configured — add daily_scan section to decisionssearch.yaml"}
        try:
            result = await scanner.run_scan(full=True)
            return {
                "prs_scanned": result.prs_scanned,
                "prs_new": result.prs_new,
                "cards_scanned": result.cards_scanned,
                "cards_new": result.cards_new,
                "errors": result.errors,
            }
        except Exception as e:
            return _as_error(e)


def register_operator_tools(app: FastMCP, c: ServiceContainer) -> None:
    """Registra capacidades do operador em uma superfície separada do agente."""

    @app.tool(name="memory.change.approve")
    async def memory_change_approve(
        proposal_id: str,
        preview_hash: str,
        principal_id: str,
        principal_token: str | None = None,
        comment: str = "",
    ) -> dict:
        if not _ledger_enabled(c):
            return {"error": "Versioned memory ledger is not configured"}
        try:
            principal_id = TrustedOperatorResolver.from_env().resolve(principal_id, principal_token)
            approval = await c.approval_boundary.approve(
                uuid.UUID(proposal_id),
                principal_id=principal_id,
                principal_type="operator",
                preview_hash=preview_hash,
                comment=comment,
            )
            return _json_ready(approval)
        except Exception as error:
            return _as_error(error)

    @app.tool(name="memory.change.reject")
    async def memory_change_reject(
        proposal_id: str,
        reason: str,
        principal_id: str,
        principal_token: str | None = None,
    ) -> dict:
        if not _ledger_enabled(c):
            return {"error": "Versioned memory ledger is not configured"}
        try:
            operator_id = TrustedOperatorResolver.from_env().resolve(principal_id, principal_token)
            proposal = await c.approval_boundary.reject(
                uuid.UUID(proposal_id),
                reason,
                principal_id=operator_id,
            )
            return _json_ready(proposal)
        except Exception as error:
            return _as_error(error)

    @app.tool(name="memory.change.apply")
    async def memory_change_apply(
        proposal_id: str,
        approval_id: str,
        principal_id: str,
        principal_token: str | None = None,
    ) -> dict:
        if not _ledger_enabled(c):
            return {"error": "Versioned memory ledger is not configured"}
        try:
            operator_id = TrustedOperatorResolver.from_env().resolve(principal_id, principal_token)
            approval = await c.ledger.get_approval(uuid.UUID(approval_id))
            if approval is None or approval.proposal_id != uuid.UUID(proposal_id):
                return {"error": "Approval not found", "status": "rejected"}
            if approval.principal_id != operator_id:
                return {"error": "Only the approving operator may apply this change", "status": "rejected"}
            result = await c.ledger_apply.apply(uuid.UUID(proposal_id), uuid.UUID(approval_id))
            proposal = await c.ledger.get_proposal(uuid.UUID(proposal_id))
            result_payload = _json_ready(result)
            legacy_id = ""
            if proposal.after is not None:
                legacy_id = dict(proposal.after.legacy_ids).get("memory_id", "")
            return {
                **result_payload,
                "status": "applied",
                "proposal_id": proposal_id,
                "approval_id": approval_id,
                "preview_hash": proposal.preview_hash,
                "memory_id": legacy_id or result_payload.get("memory_id"),
                "result": result_payload,
            }
        except Exception as error:
            return _as_error(error)
