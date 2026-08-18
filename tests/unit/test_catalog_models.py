import pytest
from pydantic import ValidationError

from decisionssearch.domain import (
    AliasSpec,
    CatalogConflictError,
    CatalogImportError,
    CatalogNotFoundError,
    CatalogNode,
    CatalogStatus,
    CatalogValidationError,
    CategoryNode,
    CreateCategoryCommand,
    CreateDomainCommand,
    CreateManualMemoryCommand,
    CreateProjectCommand,
    CreateRelationCommand,
    DeleteRelationCommand,
    DomainNode,
    MemoryServiceError,
    ProjectNode,
    RelationSpec,
    UpdateCategoryCommand,
    UpdateDomainCommand,
    UpdateProjectCommand,
)


def test_create_project_command_normalizes_slug_and_deduplicates_lists() -> None:
    command = CreateProjectCommand(
        slug=" Core-Platform ",
        name="Core Platform",
        description="Main project",
        aliases=[" Core ", "core", "Core", "", "core "],
        tags=[" ML ", "ml", "Ml "],
    )

    assert command.slug == "core-platform"
    assert command.aliases == ["Core", "core"]
    assert command.tags == ["ML"]


def test_project_node_normalizes_slug() -> None:
    node = ProjectNode(
        id="proj-1",
        slug=" Core-Platform ",
        name="Core Platform",
        description="Main project",
    )

    assert node.slug == "core-platform"


def test_project_node_preserves_alias_casing_and_deduplicates_exact_values() -> None:
    node = ProjectNode(
        id="proj-1",
        slug="core-platform",
        name="Core Platform",
        aliases=["API", "Api", "API", " api "],
        tags=[" ML ", "ml", "Ml "],
    )

    assert node.aliases == ["API", "Api", "api"]
    assert node.tags == ["ML"]


def test_manual_memory_command_deduplicates_domain_case_insensitively() -> None:
    command = CreateManualMemoryCommand(
        project="CORE",
        category="DesignPattern",
        domain=[" Billing ", "billing", "BILLING "],
        title="Forms Pattern",
        summary="Use forms",
        details="",
    )

    assert command.domain == ["Billing"]


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ProjectNode(id=123, slug="core-platform", name="Core Platform"),
        lambda: CategoryNode(
            id="cat-1",
            slug="core-platform",
            name="Core Platform",
            project_id=456,
        ),
        lambda: DomainNode(
            id="dom-1",
            slug="core-platform",
            name="Core Platform",
            project_id=456,
        ),
        lambda: AliasSpec(node_id="node-1", value="Alias", kind=123),
        lambda: RelationSpec(
            source_id=123,
            source_kind="project",
            relation_type="RELATED_TO",
            target_id="cat-1",
            target_kind="category",
            rationale="link",
        ),
    ],
)
def test_identity_and_scope_fields_reject_non_string_types(factory) -> None:
    with pytest.raises(ValidationError):
        factory()


@pytest.mark.parametrize(
    "factory",
    [
        lambda: CreateProjectCommand(slug=123, name="Core Platform"),
        lambda: UpdateProjectCommand(id=123, slug="core-platform", name="Core Platform"),
        lambda: CreateCategoryCommand(
            slug="core-platform",
            name="Core Platform",
            project_id=123,
        ),
        lambda: UpdateCategoryCommand(
            id=123,
            slug="core-platform",
            name="Core Platform",
            project_id="proj-1",
        ),
        lambda: CreateDomainCommand(
            slug="core-platform",
            name="Core Platform",
            project_id=123,
        ),
        lambda: UpdateDomainCommand(
            id=123,
            slug="core-platform",
            name="Core Platform",
            project_id="proj-1",
        ),
        lambda: CreateRelationCommand(
            source_id=123,
            source_kind="project",
            relation_type="RELATED_TO",
            target_id="cat-1",
            target_kind="category",
            rationale="link",
        ),
        lambda: DeleteRelationCommand(
            source_id="proj-1",
            source_kind=123,
            relation_type="RELATED_TO",
            target_id="cat-1",
            target_kind="category",
        ),
        lambda: CreateManualMemoryCommand(
            project=123,
            category="DesignPattern",
            domain=["ML"],
            title="Forms Pattern",
            summary="Use forms",
        ),
    ],
)
def test_command_fields_reject_non_string_types(factory) -> None:
    with pytest.raises(ValidationError):
        factory()


def test_project_node_rejects_invalid_slug() -> None:
    with pytest.raises(ValidationError):
        ProjectNode(
            id="proj-1",
            slug="core platform",
            name="Core Platform",
        )


def test_project_node_validates_status() -> None:
    with pytest.raises(ValidationError):
        ProjectNode(
            id="proj-1",
            slug="core-platform",
            name="Core Platform",
            status="archived",
        )


def test_relation_spec_rejects_relation_type_outside_whitelist() -> None:
    with pytest.raises(ValidationError):
        RelationSpec(
            source_id="proj-1",
            source_kind="project",
            relation_type="USES",
            target_id="cat-1",
            target_kind="category",
            rationale="invalid relation",
        )


def test_catalog_exceptions_capture_metadata() -> None:
    validation_error = CatalogValidationError(
        "invalid slug",
        field="slug",
        value="Core Platform",
        context={"slug": "Core Platform"},
    )
    conflict_error = CatalogConflictError(
        "slug already exists",
        resource="project",
        identifier="core-platform",
        context={"slug": "core-platform"},
    )
    not_found_error = CatalogNotFoundError(
        "project not found",
        resource="project",
        identifier="missing",
        context={"id": "missing"},
    )
    import_error = CatalogImportError(
        "csv invalid",
        source="csv",
        row=7,
        context={"file": "catalog.csv"},
    )

    assert isinstance(validation_error, MemoryServiceError)
    assert isinstance(conflict_error, MemoryServiceError)
    assert isinstance(not_found_error, MemoryServiceError)
    assert isinstance(import_error, MemoryServiceError)
    assert validation_error.field == "slug"
    assert validation_error.value == "Core Platform"
    assert conflict_error.resource == "project"
    assert conflict_error.identifier == "core-platform"
    assert not_found_error.resource == "project"
    assert not_found_error.identifier == "missing"
    assert import_error.source == "csv"
    assert import_error.row == 7


def test_manual_memory_command_accepts_modules_and_type_specific_fields() -> None:
    command = CreateManualMemoryCommand(
        project="CORE",
        category="BusinessRule",
        domain=["Billing"],
        modules=["faturamento", "TUSD"],
        title="TUSD billing rule",
        summary="TUSD must be billed monthly",
        details="All TUSD charges are billed on a monthly cycle.",
        event_date="2026-04-22T10:00:00",
    )

    assert command.modules == ["faturamento", "TUSD"]
    assert command.event_date == "2026-04-22T10:00:00"


def test_manual_memory_command_code_pattern_requires_examples() -> None:
    with pytest.raises(ValidationError, match="CodePattern requires at least one example"):
        CreateManualMemoryCommand(
            project="CORE",
            category="CodePattern",
            title="Some pattern",
            summary="A pattern",
            details="Pattern details",
            examples=[],
        )


def test_manual_memory_command_code_pattern_with_examples_succeeds() -> None:
    command = CreateManualMemoryCommand(
        project="CORE",
        category="CodePattern",
        title="Guard Clauses",
        summary="Use guard clauses for early return",
        details="Prefer early returns over nested conditionals",
        examples=["services/auth_service.py:validate_token"],
    )

    assert command.examples == ["services/auth_service.py:validate_token"]


def test_manual_memory_command_architectural_decision_requires_alternatives() -> None:
    with pytest.raises(
        ValidationError, match="ArchitecturalDecision requires at least one alternative"
    ):
        CreateManualMemoryCommand(
            project="CORE",
            category="ArchitecturalDecision",
            title="Use PostgreSQL",
            summary="Chose PostgreSQL over alternatives",
            details="PostgreSQL selected for relational data",
            alternatives_considered=[],
        )


def test_manual_memory_command_architectural_decision_with_alternatives_succeeds() -> None:
    command = CreateManualMemoryCommand(
        project="CORE",
        category="ArchitecturalDecision",
        title="Use PostgreSQL",
        summary="Chose PostgreSQL over alternatives",
        details="PostgreSQL selected for relational data",
        alternatives_considered=["MongoDB — descartado por falta de joins complexos"],
    )

    assert command.alternatives_considered == [
        "MongoDB — descartado por falta de joins complexos"
    ]


def test_manual_memory_command_business_rule_does_not_require_examples_or_alternatives() -> None:
    command = CreateManualMemoryCommand(
        project="CORE",
        category="BusinessRule",
        domain=["Billing"],
        title="Monthly billing",
        summary="All charges are monthly",
    )

    assert command.examples == []
    assert command.alternatives_considered == []


def test_catalog_contracts_are_exported() -> None:
    assert CatalogNode is not None
    assert CatalogStatus is not None
    assert CategoryNode is not None
    assert DomainNode is not None
    assert AliasSpec is not None
    assert UpdateProjectCommand is not None
    assert UpdateCategoryCommand is not None
    assert UpdateDomainCommand is not None
    assert CreateProjectCommand is not None
    assert CreateCategoryCommand is not None
    assert CreateDomainCommand is not None
    assert CreateRelationCommand is not None
    assert DeleteRelationCommand is not None
    assert CreateManualMemoryCommand is not None
