from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from decisionssearch.domain.catalog.catalog_nodes import CatalogRelationType, CatalogStatus
from decisionssearch.domain.catalog.catalog_validation import (
    normalize_optional_text,
    normalize_required_text,
    normalize_semantic_strings,
    normalize_slug,
    normalize_unique_aliases,
)


class _CatalogCommandBase(BaseModel):
    slug: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    status: CatalogStatus = CatalogStatus.ACTIVE
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("slug", mode="before")
    @classmethod
    def normalize_slug_field(cls, value: object) -> str:
        return normalize_slug(value)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name_field(cls, value: object) -> str:
        return normalize_required_text(value, "name")

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description_field(cls, value: object) -> str:
        return normalize_optional_text(value, "description")

    @field_validator("aliases", mode="before")
    @classmethod
    def normalize_aliases(cls, value: object) -> list[str]:
        return normalize_unique_aliases(value)

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: object) -> list[str]:
        return normalize_semantic_strings(value)


class _ScopedCatalogCommandBase(_CatalogCommandBase):
    project_id: str = Field(min_length=1)

    @field_validator("project_id", mode="before")
    @classmethod
    def normalize_project_id_field(cls, value: object) -> str:
        return normalize_required_text(value, "project_id")


class CreateProjectCommand(_CatalogCommandBase):
    pass


class UpdateProjectCommand(_CatalogCommandBase):
    id: str = Field(min_length=1)

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id_field(cls, value: object) -> str:
        return normalize_required_text(value, "id")


class CreateCategoryCommand(_ScopedCatalogCommandBase):
    pass


class UpdateCategoryCommand(_ScopedCatalogCommandBase):
    id: str = Field(min_length=1)

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id_field(cls, value: object) -> str:
        return normalize_required_text(value, "id")


class CreateDomainCommand(_ScopedCatalogCommandBase):
    pass


class UpdateDomainCommand(_ScopedCatalogCommandBase):
    id: str = Field(min_length=1)

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id_field(cls, value: object) -> str:
        return normalize_required_text(value, "id")


class CreateRelationCommand(BaseModel):
    source_id: str = Field(min_length=1)
    source_kind: str = Field(min_length=1)
    relation_type: CatalogRelationType
    target_id: str = Field(min_length=1)
    target_kind: str = Field(min_length=1)
    rationale: str = ""

    @field_validator("source_id", "source_kind", "target_id", "target_kind", mode="before")
    @classmethod
    def normalize_required_fields(cls, value: object, info) -> str:
        return normalize_required_text(value, info.field_name)

    @field_validator("rationale", mode="before")
    @classmethod
    def normalize_rationale_field(cls, value: object) -> str:
        return normalize_optional_text(value, "rationale")


class DeleteRelationCommand(BaseModel):
    source_id: str = Field(min_length=1)
    source_kind: str = Field(min_length=1)
    relation_type: CatalogRelationType
    target_id: str = Field(min_length=1)
    target_kind: str = Field(min_length=1)

    @field_validator("source_id", "source_kind", "target_id", "target_kind", mode="before")
    @classmethod
    def normalize_required_fields(cls, value: object, info) -> str:
        return normalize_required_text(value, info.field_name)


class CreateManualMemoryCommand(BaseModel):
    project: str = Field(min_length=1)
    category: str = Field(min_length=1)
    domain: list[str] = Field(default_factory=list)
    modules: list[str] = Field(default_factory=list)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    details: str = ""
    objective: str = ""
    trigger: str = ""
    stakeholders: list[str] = Field(default_factory=list)
    action_triggers: list[str] = Field(default_factory=list)
    related_files: list[str] = Field(default_factory=list)
    business_rules: list[str] = Field(default_factory=list)
    architectural_rationale: str = ""
    examples: list[str] = Field(default_factory=list)
    alternatives_considered: list[str] = Field(default_factory=list)
    event_date: str = ""

    @field_validator("project", "category", "title", "summary", mode="before")
    @classmethod
    def normalize_required_text_fields(cls, value: object, info) -> str:
        return normalize_required_text(value, info.field_name)

    @field_validator(
        "details",
        "objective",
        "trigger",
        "architectural_rationale",
        "event_date",
        mode="before",
    )
    @classmethod
    def normalize_optional_text_fields(cls, value: object, info) -> str:
        return normalize_optional_text(value, info.field_name)

    @field_validator(
        "domain",
        "modules",
        "stakeholders",
        "action_triggers",
        "related_files",
        "business_rules",
        "examples",
        "alternatives_considered",
        mode="before",
    )
    @classmethod
    def normalize_list_fields(cls, value: object) -> list[str]:
        return normalize_semantic_strings(value)

    @model_validator(mode="after")
    def validate_type_specific_fields(self) -> "CreateManualMemoryCommand":
        if self.category == "FeatureDescription" and not (
            self.objective or self.trigger or self.related_files
        ):
            raise ValueError(
                "FeatureDescription requires objective, trigger or related_files"
            )
        if self.category == "BusinessRule" and not self.domain:
            raise ValueError("BusinessRule requires at least one domain")
        if self.category == "CodePattern" and not self.examples:
            raise ValueError("CodePattern requires at least one example")
        if self.category == "ArchitecturalDecision" and not self.alternatives_considered:
            raise ValueError(
                "ArchitecturalDecision requires at least one alternative considered"
            )
        return self
