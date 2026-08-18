from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from decisionssearch.domain.catalog.catalog_validation import (
    normalize_optional_text,
    normalize_required_text,
    normalize_semantic_strings,
    normalize_slug,
    normalize_unique_aliases,
)

CatalogRelationType = Literal[
    "HAS_CATEGORY",
    "HAS_DOMAIN",
    "IN_PROJECT",
    "IN_CATEGORY",
    "ABOUT_DOMAIN",
    "RELATED_TO",
    "DEPENDS_ON",
    "REFINES",
    "DEPRECATES",
    "CONFLICTS_WITH",
    "EVOLVES_FROM",
]


class CatalogStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class CatalogNode(BaseModel):
    id: str = Field(min_length=1, description="Identificador estavel")
    slug: str = Field(min_length=1, description="Slug canonicamente normalizado")
    name: str = Field(min_length=1, description="Campo de apresentacao")
    description: str = ""
    status: CatalogStatus = CatalogStatus.ACTIVE
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("id", "name", mode="before")
    @classmethod
    def strip_required_text_fields(cls, value: object, info) -> str:
        return normalize_required_text(value, info.field_name)

    @field_validator("description", mode="before")
    @classmethod
    def strip_description_field(cls, value: object) -> str:
        return normalize_optional_text(value, "description")

    @field_validator("slug", mode="before")
    @classmethod
    def normalize_slug_field(cls, value: object) -> str:
        return normalize_slug(value)

    @field_validator("aliases", mode="before")
    @classmethod
    def normalize_aliases(cls, value: object) -> list[str]:
        return normalize_unique_aliases(value)

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: object) -> list[str]:
        return normalize_semantic_strings(value)


class ProjectNode(CatalogNode):
    pass


class CategoryNode(CatalogNode):
    project_id: str = Field(min_length=1, description="Projeto pai")

    @field_validator("project_id", mode="before")
    @classmethod
    def strip_project_id(cls, value: object) -> str:
        return normalize_required_text(value, "project_id")


class DomainNode(CatalogNode):
    project_id: str = Field(min_length=1, description="Projeto pai")

    @field_validator("project_id", mode="before")
    @classmethod
    def strip_project_id(cls, value: object) -> str:
        return normalize_required_text(value, "project_id")


class AliasSpec(BaseModel):
    node_id: str = Field(min_length=1)
    value: str = Field(min_length=1)
    kind: str = Field(min_length=1)

    @field_validator("kind", "node_id", "value", mode="before")
    @classmethod
    def strip_text_fields(cls, value: object, info) -> str:
        return normalize_required_text(value, info.field_name)


class RelationSpec(BaseModel):
    source_id: str = Field(min_length=1)
    source_kind: str = Field(min_length=1)
    relation_type: CatalogRelationType
    target_id: str = Field(min_length=1)
    target_kind: str = Field(min_length=1)
    rationale: str = ""

    @field_validator("source_id", "source_kind", "target_id", "target_kind", mode="before")
    @classmethod
    def strip_required_text_fields(cls, value: object, info) -> str:
        return normalize_required_text(value, info.field_name)

    @field_validator("rationale", mode="before")
    @classmethod
    def strip_rationale_field(cls, value: object) -> str:
        return normalize_optional_text(value, "rationale")
