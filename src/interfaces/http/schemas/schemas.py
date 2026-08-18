from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CatalogNodeResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    slug: str
    name: str
    description: str = ""
    status: str = "active"
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    project_id: str | None = None


class OperationStatusResponse(BaseModel):
    status: str = "ok"


class CatalogCsvBundleResponse(BaseModel):
    schema_version: str
    projects_csv: str
    categories_csv: str
    domains_csv: str
    relations_csv: str


class CatalogCsvImportRequest(CatalogCsvBundleResponse):
    model_config = ConfigDict(extra="forbid")


class CatalogCsvImportResponse(BaseModel):
    status: str = "ok"
    schema_version: str
    imported: dict[str, int] = Field(default_factory=dict)


class PRMemoryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str | None = None
    repo: str
    pr_number: int
    title: str
    summary: str
    objective: str = ""
    changed_files: list[str] = Field(default_factory=list)
    pr_url: str = Field(min_length=1)
    work_item_url: str = Field(min_length=1)
    branch: str = ""
    work_item_id: str = ""
    work_item_summary: str = ""
    work_item_provider: str = ""
    areas: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)
    status: str = "open"
    merged_at: str = ""
    event_date: str = ""


class PRMemoryResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str = "applied"
    memory_id: str | None = None
    family_id: str | None = None
    revision_id: str | None = None
    proposal_id: str | None = None
    preview_hash: str = ""
    requires_human_approval: bool = False
    project: str = ""
    repo: str = ""
    pr_number: int = 0
    title: str = ""
    summary: str = ""
    objective: str = ""
    changed_files: list[str] = Field(default_factory=list)
    pr_url: str = ""
    branch: str = ""
    work_item_id: str = ""
    work_item_url: str = ""
    work_item_summary: str = ""
    work_item_provider: str = ""
    areas: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)
    pr_status: str = "open"
    merged_at: str = ""
    event_date: str = ""
    touches_frontend: bool = False
    touches_backend: bool = False
    related_pr_candidates: list[dict] = Field(default_factory=list)
    before: list[dict] = Field(default_factory=list)
    after: dict | None = None
    field_diff: list[dict] = Field(default_factory=list)
    proposed_legacy_id: str = ""


class ManualMemoryResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    # Compatibilidade de leitura: uma nova escrita retorna proposal_id e não
    # fabrica memory_id/revision_id antes da aprovação.
    memory_id: str | None = None
    family_id: str | None = None
    revision_id: str | None = None
    proposal_id: str | None = None
    project: str = ""
    category: str = ""
    domain: list[str] = Field(default_factory=list)
    modules: list[str] = Field(default_factory=list)
    title: str = ""
    summary: str = ""
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
    event_date: datetime | None = None
    status: str = "proposed"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    valid_at: datetime | None = None
    invalid_at: datetime | None = None
    access_count: int = 0
    weight_manual: float = 0.5
    weight_confidence: float = 0.5
    weight_usage: float = 0.0
    weight_feedback: float = 0.0
    effective_weight: float = 0.5
    source_hash: str = ""
    evidence_count: int = 0
    requires_human_approval: bool = False
    preview_hash: str = ""
    before: list[dict] = Field(default_factory=list)
    after: dict | None = None
    field_diff: list[dict] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    reason: str = ""
    question: str = ""


class MemoryChangeApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_hash: str = Field(min_length=1)
    comment: str = ""


class MemoryChangeRejectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)


class MemoryChangeApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(min_length=1)


class CatalogProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    description: str = ""
    status: str = "active"
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class CatalogProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    description: str = ""
    status: str = "active"
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class CatalogCategoryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    description: str = ""
    status: str = "active"
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    project_id: str


class CatalogDomainCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    description: str = ""
    status: str = "active"
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    project_id: str


class CatalogRelationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    source_kind: str
    relation_type: str
    target_id: str
    target_kind: str
    rationale: str = ""


class CatalogRelationDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    source_kind: str
    relation_type: str
    target_id: str
    target_kind: str


class ManualMemoryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str | None = None
    category: str
    domain: list[str] = Field(default_factory=list)
    modules: list[str] = Field(default_factory=list)
    title: str
    summary: str
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
