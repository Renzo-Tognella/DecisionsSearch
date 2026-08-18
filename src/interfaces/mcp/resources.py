from __future__ import annotations

import json

from decisionssearch.domain.shared.exceptions import MemoryServiceError
from decisionssearch.domain.memory_ledger import MemoryScope
from decisionssearch.application.memory.ledger.views import revision_to_legacy_view
from decisionssearch.bootstrap.container import ServiceContainer
from decisionssearch.interfaces.mcp.mcp_compat import FastMCP


def _format_items(items: list[dict]) -> str:
    if not items:
        return "Nenhum item encontrado."

    lines: list[str] = []
    for index, item in enumerate(items, 1):
        memory = item.get("memory") or item
        lines.append(f"### {index}. {memory.get('title', 'Sem titulo')}")
        lines.append(f"**Peso:** {float(memory.get('effective_weight', 0.0)):.2f}")
        if memory.get("summary"):
            lines.append(str(memory["summary"]))
        lines.append("")
    return "\n".join(lines).strip()


def _json_payload(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _error_payload(error: Exception) -> str:
    return _json_payload({"error": str(error), "type": type(error).__name__})


async def _semantic_ledger_items(
    container: ServiceContainer,
    *,
    project: str | None = None,
    category: str | None = None,
) -> list[dict] | None:
    """Lê memórias semânticas do ledger quando o container o expõe.

    ``None`` mantém compatibilidade com containers legados/test doubles que ainda
    não possuem o adapter versionado; o caminho canônico nunca cai nesse ramo.
    """

    ledger = getattr(container, "ledger", None)
    if ledger is None or not hasattr(ledger, "list_effective_revisions"):
        return None
    revisions = await ledger.list_effective_revisions(
        project=project,
        category=category,
        memory_scope=MemoryScope.SEMANTIC,
        memory_branch="semantic",
    )
    return [revision_to_legacy_view(revision) for revision in reversed(revisions)]


def register_resources(app: FastMCP, c: ServiceContainer) -> None:
    @app.resource("meta://tools/version")
    async def tools_version() -> str:
        """Versão da superfície de tools MCP (G9)."""
        from decisionssearch.interfaces.mcp.tools import TOOL_SURFACE_VERSION

        return _json_payload({"tool_surface_version": TOOL_SURFACE_VERSION})

    @app.resource("graph://projects")
    async def graph_projects() -> str:
        try:
            return _json_payload(await c.graph_catalog.list_projects())
        except MemoryServiceError as error:
            return _error_payload(error)

    @app.resource("graph://project/{project_slug}/categories")
    async def graph_project_categories(project_slug: str) -> str:
        try:
            project = await c.graph_catalog.get_project(project_slug)
            if not project:
                return _json_payload([])
            project_keys = {project.get("id"), project.get("slug"), project_slug}
            categories = await c.graph_catalog.list_categories()
            filtered = [item for item in categories if item.get("project_id") in project_keys]
            return _json_payload(filtered)
        except MemoryServiceError as error:
            return _error_payload(error)

    @app.resource("graph://project/{project_slug}/domains")
    async def graph_project_domains(project_slug: str) -> str:
        try:
            project = await c.graph_catalog.get_project(project_slug)
            if not project:
                return _json_payload([])
            project_keys = {project.get("id"), project.get("slug"), project_slug}
            domains = await c.graph_catalog.list_domains()
            filtered = [item for item in domains if item.get("project_id") in project_keys]
            return _json_payload(filtered)
        except MemoryServiceError as error:
            return _error_payload(error)

    @app.resource("graph://catalog/summary")
    async def graph_catalog_summary() -> str:
        try:
            return _json_payload(await c.graph_operations.catalog_summary())
        except MemoryServiceError as error:
            return _error_payload(error)

    @app.resource("graph://relations/allowed")
    async def graph_relations_allowed() -> str:
        try:
            return _json_payload(await c.graph_operations.list_allowed_relations())
        except MemoryServiceError as error:
            return _error_payload(error)

    @app.resource("mem://projects")
    async def list_projects() -> str:
        """Lista projetos registrados no grafo."""
        try:
            results = await c.neo4j.list_projects()
            return "\n".join(f"- {project}" for project in results) or "Nenhum projeto registrado."
        except MemoryServiceError as error:
            return f"Erro ao listar projetos: {error}"

    @app.resource("mem://project/{project}/top-design-rules")
    async def top_design_rules(project: str) -> str:
        """Top DesignRules por projeto."""
        try:
            items = await _semantic_ledger_items(c, project=project, category="DesignRule")
            if items is None:
                items = await c.neo4j.query_by_project(project, category="DesignRule", limit=10)
            return _format_items(items)
        except MemoryServiceError as error:
            return f"Erro ao consultar design rules: {error}"

    @app.resource("mem://project/{project}/top-patterns")
    async def top_patterns(project: str) -> str:
        """Top DesignPatterns por projeto."""
        try:
            items = await _semantic_ledger_items(c, project=project, category="DesignPattern")
            if items is None:
                items = await c.neo4j.query_by_project(project, category="DesignPattern", limit=10)
            return _format_items(items)
        except MemoryServiceError as error:
            return f"Erro ao consultar patterns: {error}"

    @app.resource("mem://domain/{domain}/rules")
    async def domain_rules(domain: str) -> str:
        """Regras por domínio."""
        try:
            items = await _semantic_ledger_items(c, category="BusinessRule")
            if items is not None:
                items = [item for item in items if domain in item.get("domain", [])][:10]
            else:
                items = await c.neo4j.query_by_domain(domain, category="BusinessRule", limit=10)
            return _format_items(items)
        except MemoryServiceError as error:
            return f"Erro ao consultar regras por dominio: {error}"

    @app.resource("mem://pr/{pr_memory_id}/related-memories")
    async def pr_related_memories(pr_memory_id: str) -> str:
        """MemoryItems linkados a um PR."""
        try:
            items = await c.pr_memory.query_pr_linked_memories(pr_memory_id)
            if not items:
                return "Nenhuma memória linkada a este PR."
            lines: list[str] = []
            for idx, item in enumerate(items, 1):
                lines.append(f"### {idx}. {item.get('title', 'Sem titulo')}")
                lines.append(f"**Relação:** {item.get('relation_type', 'N/A')}")
                if item.get("rationale"):
                    lines.append(f"**Racional:** {item['rationale']}")
                if item.get("summary"):
                    lines.append(str(item["summary"]))
                lines.append("")
            return "\n".join(lines).strip()
        except MemoryServiceError as error:
            return f"Erro ao consultar memorias do PR: {error}"

    @app.resource("mem://memory/{memory_id}/related-prs")
    async def memory_related_prs(memory_id: str) -> str:
        """PRs linkados a um MemoryItem."""
        try:
            items = await c.pr_memory.query_memory_linked_prs(memory_id)
            if not items:
                return "Nenhum PR linkado a esta memória."
            lines: list[str] = []
            for idx, item in enumerate(items, 1):
                pr_num = item.get('pr_number', '?')
                title = item.get('title', 'Sem titulo')
                lines.append(f"### {idx}. PR #{pr_num} — {title}")
                repo = item.get('repo', 'N/A')
                rel = item.get('relation_type', 'N/A')
                lines.append(f"**Repo:** {repo} · **Relação:** {rel}")
                lines.append("")
            return "\n".join(lines).strip()
        except MemoryServiceError as error:
            return f"Erro ao consultar PRs da memoria: {error}"
