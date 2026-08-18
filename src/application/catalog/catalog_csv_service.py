from __future__ import annotations

import csv
import io
from collections.abc import Mapping

from decisionssearch.domain import (
    CatalogImportError,
    CreateCategoryCommand,
    CreateDomainCommand,
    CreateProjectCommand,
    CreateRelationCommand,
)
from decisionssearch.domain.catalog.catalog_validation import normalize_slug


class CatalogCsvService:
    SCHEMA_VERSION = "1"

    PROJECT_COLUMNS = ("id", "slug", "name", "description", "status", "aliases", "tags")
    NODE_COLUMNS = ("id", "slug", "name", "description", "status", "aliases", "tags", "project_id")
    RELATION_COLUMNS = (
        "source_id",
        "source_kind",
        "relation_type",
        "target_id",
        "target_kind",
        "rationale",
    )

    def __init__(self, graph_catalog, graph_operations) -> None:  # noqa: ANN001
        self.graph_catalog = graph_catalog
        self.graph_operations = graph_operations

    async def export_projects_csv(self) -> str:
        return self._write_csv(
            self.PROJECT_COLUMNS,
            await self.graph_catalog.list_projects(),
        )

    async def export_categories_csv(self) -> str:
        return self._write_csv(
            self.NODE_COLUMNS,
            await self.graph_catalog.list_categories(),
        )

    async def export_domains_csv(self) -> str:
        return self._write_csv(
            self.NODE_COLUMNS,
            await self.graph_catalog.list_domains(),
        )

    async def export_relations_csv(self) -> str:
        return self._write_csv(
            self.RELATION_COLUMNS,
            await self.graph_operations.list_relations(),
        )

    async def export_catalog_csv_bundle(self) -> dict[str, str]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "projects_csv": await self.export_projects_csv(),
            "categories_csv": await self.export_categories_csv(),
            "domains_csv": await self.export_domains_csv(),
            "relations_csv": await self.export_relations_csv(),
        }

    async def import_catalog_csv_bundle(self, bundle: Mapping[str, str]) -> dict[str, object]:
        schema_version = str(bundle.get("schema_version", "")).strip()
        if schema_version != self.SCHEMA_VERSION:
            raise CatalogImportError(
                "schema_version invalida para importacao do catalogo",
                source="bundle",
                context={"schema_version": schema_version},
            )

        projects = self._parse_csv(
            "projects_csv", bundle.get("projects_csv", ""), self.PROJECT_COLUMNS,
        )
        categories = self._parse_csv(
            "categories_csv", bundle.get("categories_csv", ""), self.NODE_COLUMNS,
        )
        domains = self._parse_csv(
            "domains_csv", bundle.get("domains_csv", ""), self.NODE_COLUMNS,
        )
        relations = self._parse_csv(
            "relations_csv", bundle.get("relations_csv", ""), self.RELATION_COLUMNS,
        )

        project_refs = self._known_project_refs(await self.graph_catalog.list_projects())
        node_refs = self._known_node_refs(
            await self.graph_catalog.list_projects(),
            await self.graph_catalog.list_categories(),
            await self.graph_catalog.list_domains(),
        )

        imported_project_refs = self._validate_projects(projects)
        project_refs.update(imported_project_refs)
        node_refs.update(imported_project_refs)

        imported_category_refs = self._validate_scoped_nodes(
            categories, source="categories_csv", project_refs=project_refs,
        )
        imported_domain_refs = self._validate_scoped_nodes(
            domains, source="domains_csv", project_refs=project_refs,
        )
        node_refs.update(imported_category_refs)
        node_refs.update(imported_domain_refs)

        self._validate_relations(relations, node_refs=node_refs)

        for row in projects:
            await self.graph_catalog.create_project(self._project_command(row))
        for row in categories:
            await self.graph_catalog.create_category(self._category_command(row))
        for row in domains:
            await self.graph_catalog.create_domain(self._domain_command(row))
        for row in relations:
            await self.graph_operations.create_relation(self._relation_command(row))

        return {
            "status": "ok",
            "schema_version": self.SCHEMA_VERSION,
            "imported": {
                "projects": len(projects),
                "categories": len(categories),
                "domains": len(domains),
                "relations": len(relations),
            },
        }

    def _validate_projects(self, rows: list[dict[str, str]]) -> set[str]:
        refs: set[str] = set()
        for index, row in enumerate(rows, start=2):
            self._validate_slug(row["slug"], source="projects_csv", row_number=index)
            self._require(row["name"], source="projects_csv", row_number=index, field="name")
            refs.update(self._row_refs(row))
        return refs

    def _validate_scoped_nodes(
        self,
        rows: list[dict[str, str]],
        *,
        source: str,
        project_refs: set[str],
    ) -> set[str]:
        refs: set[str] = set()
        for index, row in enumerate(rows, start=2):
            self._validate_slug(row["slug"], source=source, row_number=index)
            self._require(row["name"], source=source, row_number=index, field="name")
            project_id = self._require(
                row["project_id"], source=source, row_number=index, field="project_id",
            )
            if project_id not in project_refs:
                raise CatalogImportError(
                    f"project_id invalido no catalogo: {project_id}",
                    source=source,
                    row=index,
                    context={"project_id": project_id},
                )
            refs.update(self._row_refs(row))
        return refs

    def _validate_relations(self, rows: list[dict[str, str]], *, node_refs: set[str]) -> None:
        for index, row in enumerate(rows, start=2):
            source_id = self._require(
                row["source_id"], source="relations_csv",
                row_number=index, field="source_id",
            )
            target_id = self._require(
                row["target_id"], source="relations_csv",
                row_number=index, field="target_id",
            )
            self._require(
                row["source_kind"], source="relations_csv",
                row_number=index, field="source_kind",
            )
            self._require(
                row["target_kind"], source="relations_csv",
                row_number=index, field="target_kind",
            )
            self._require(
                row["relation_type"], source="relations_csv",
                row_number=index, field="relation_type",
            )
            if source_id not in node_refs or target_id not in node_refs:
                raise CatalogImportError(
                    "referencia de relacao invalida no catalogo",
                    source="relations_csv",
                    row=index,
                    context={"source_id": source_id, "target_id": target_id},
                )

    def _project_command(self, row: dict[str, str]) -> CreateProjectCommand:
        return CreateProjectCommand(
            slug=row["slug"],
            name=row["name"],
            description=row["description"],
            status=row["status"] or "active",
            aliases=self._split_list(row["aliases"]),
            tags=self._split_list(row["tags"]),
        )

    def _category_command(self, row: dict[str, str]) -> CreateCategoryCommand:
        return CreateCategoryCommand(
            slug=row["slug"],
            name=row["name"],
            description=row["description"],
            status=row["status"] or "active",
            aliases=self._split_list(row["aliases"]),
            tags=self._split_list(row["tags"]),
            project_id=row["project_id"],
        )

    def _domain_command(self, row: dict[str, str]) -> CreateDomainCommand:
        return CreateDomainCommand(
            slug=row["slug"],
            name=row["name"],
            description=row["description"],
            status=row["status"] or "active",
            aliases=self._split_list(row["aliases"]),
            tags=self._split_list(row["tags"]),
            project_id=row["project_id"],
        )

    def _relation_command(self, row: dict[str, str]) -> CreateRelationCommand:
        return CreateRelationCommand(
            source_id=row["source_id"],
            source_kind=row["source_kind"],
            relation_type=row["relation_type"],
            target_id=row["target_id"],
            target_kind=row["target_kind"],
            rationale=row["rationale"],
        )

    @staticmethod
    def _split_list(value: str) -> list[str]:
        return [item.strip() for item in value.split("|") if item.strip()]

    @staticmethod
    def _join_list(value: object) -> str:
        if isinstance(value, list):
            return "|".join(str(item) for item in value if str(item).strip())
        return str(value or "")

    @classmethod
    def _write_csv(cls, columns: tuple[str, ...], rows: list[dict]) -> str:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(columns), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            payload = {column: cls._join_list(row.get(column, "")) for column in columns}
            writer.writerow(payload)
        return buffer.getvalue()

    def _parse_csv(
        self,
        source: str,
        content: str,
        required_columns: tuple[str, ...],
    ) -> list[dict[str, str]]:
        text = content or ",".join(required_columns) + "\n"
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = tuple(reader.fieldnames or ())
        if any(column not in fieldnames for column in required_columns):
            raise CatalogImportError(
                f"colunas obrigatorias ausentes em {source}",
                source=source,
                context={
                    "required_columns": list(required_columns),
                    "fieldnames": list(fieldnames),
                },
            )
        rows: list[dict[str, str]] = []
        for row_number, row in enumerate(reader, start=2):
            normalized = {
                col: (row.get(col, "") or "").strip()
                for col in required_columns
            }
            if not any(normalized.values()):
                continue
            rows.append(normalized)
        return rows

    def _validate_slug(self, value: str, *, source: str, row_number: int) -> None:
        try:
            normalize_slug(value)
        except ValueError as error:
            raise CatalogImportError(
                f"slug invalido em {source}: {error}",
                source=source,
                row=row_number,
                context={"slug": value},
            ) from error

    def _require(self, value: str, *, source: str, row_number: int, field: str) -> str:
        normalized = value.strip()
        if normalized:
            return normalized
        raise CatalogImportError(
            f"campo obrigatorio ausente em {source}: {field}",
            source=source,
            row=row_number,
            context={"field": field},
        )

    @staticmethod
    def _row_refs(row: Mapping[str, str]) -> set[str]:
        refs = {row.get("id", "").strip(), row.get("slug", "").strip()}
        refs.discard("")
        return refs

    def _known_project_refs(self, projects: list[dict]) -> set[str]:
        refs: set[str] = set()
        for row in projects:
            refs.update(self._row_refs(row))
        return refs

    def _known_node_refs(
        self,
        projects: list[dict],
        categories: list[dict],
        domains: list[dict],
    ) -> set[str]:
        refs = self._known_project_refs(projects)
        for collection in (categories, domains):
            for row in collection:
                refs.update(self._row_refs(row))
        return refs
