from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_json(value: Any) -> str:
    """Serializa um valor de forma estável para hashes e auditoria."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    _validate_json_value(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _validate_json_value(value: Any, path: str = "$") -> None:
    """Reject values que não possuem representação JSON determinística."""

    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"valor JSON não finito em {path}")
        return
    if isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"chave JSON precisa ser texto em {path}")
            _validate_json_value(item, f"{path}.{key}")
        return
    raise ValueError(f"tipo não serializável em JSON em {path}: {type(value).__name__}")


def content_hash(content: "MemoryContent") -> str:
    # Memórias criadas antes do payload estruturado precisam manter o hash
    # histórico. Os campos novos ficam fora do envelope v1 quando vazios.
    exclude = {"payload_schema", "structured_payload_json", "legacy_ids"}
    # ``weight_manual`` foi adicionado depois da primeira versão do ledger.
    # Snapshots que não o carregavam precisam manter o hash histórico.
    if content.weight_manual is None:
        exclude.add("weight_manual")
    if (
        content.weight_confidence == 0.5
        and content.weight_usage == 0.0
        and content.weight_feedback == 0.0
        and content.weight_contextual == 0.5
        and content.significance == 0.5
        and content.last_accessed_at is None
    ):
        exclude.update(
            {
                "weight_confidence",
                "weight_usage",
                "weight_feedback",
                "weight_contextual",
                "significance",
                "last_accessed_at",
            }
        )
    if not content.payload_schema and not content.structured_payload_json and not content.legacy_ids:
        payload = content.model_dump(
            mode="json",
            exclude=exclude,
        )
    else:
        payload = content.model_dump(
            mode="json", exclude=exclude if content.weight_manual is None else None
        )
    return "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def usage_payload_hash(
    *,
    procedure_family_id: uuid.UUID,
    procedure_revision_id: uuid.UUID,
    success: bool,
    correlation_id: str,
    actor_id: str,
    result: str,
) -> str:
    """Hash do fato de uso que o ledger consegue recalcular sozinho."""

    payload = {
        "procedure_family_id": str(procedure_family_id),
        "procedure_revision_id": str(procedure_revision_id),
        "success": success,
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "result": result,
    }
    return "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def legacy_memory_id_for_family(family_id: uuid.UUID | str) -> str:
    """ID de compatibilidade estável; não depende do título da revisão atual."""

    return hashlib.sha256(f"decisionssearch:memory-family:{family_id}".encode("utf-8")).hexdigest()[:16]


class MemoryScope(StrEnum):
    SEMANTIC = "semantic"
    EPISODIC = "episodic"
    PROCEDURAL = "procedural"
    PULL_REQUEST = "pull_request"


# O ledger não aceita um schema arbitrário apenas porque ele possui o formato
# ``name.vN``. Um schema novo precisa ser registrado e ter um adapter explícito;
# caso contrário, uma projeção pode guardar dados que nenhum consumidor sabe
# reconstruir.
KNOWN_PAYLOAD_SCHEMAS = frozenset(
    {
        "episodic.v1",
        "procedural.v1",
        "pull_request.v1",
    }
)


class RevisionState(StrEnum):
    ACTIVE = "active"
    SCHEDULED = "scheduled"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"
    CONFLICTED = "conflicted"
    ARCHIVED = "archived"


class ProposalStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    STALE = "stale"
    CONFLICTED = "conflicted"
    APPLYING = "applying"
    APPLIED = "applied"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ApprovalStatus(StrEnum):
    ISSUED = "issued"
    CONSUMED = "consumed"
    REVOKED = "revoked"


class LedgerOperation(StrEnum):
    CREATE = "create"
    CREATE_AND_LINK = "create_and_link"
    UPDATE = "update"
    MERGE = "merge"
    INVALIDATE = "invalidate"
    SUPERSEDE = "supersede"
    ARCHIVE = "archive"
    LINK = "link"
    ROLLBACK = "rollback"
    UNMERGE = "unmerge"
    RESOLVE_CONFLICT = "resolve_conflict"


class EvidenceStance(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXT = "context"


class EvidenceVerification(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    CONTRADICTED = "contradicted"
    UNAVAILABLE = "unavailable"


class ConflictStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
    STALE = "stale"


class ConflictDetectionCoverage(StrEnum):
    COMPLETE_NO_CONFLICT = "complete_no_conflict"
    CONFLICT_FOUND = "conflict_found"
    INCOMPLETE = "incomplete"
    UNKNOWN = "unknown"


class MemoryAliasStatus(StrEnum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"
    RETIRED = "retired"


class FamilyState(StrEnum):
    ACTIVE = "active"
    MERGED = "merged"
    RETIRED = "retired"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    APPLIED = "applied"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class RelationState(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"
    CONFLICTED = "conflicted"


KNOWN_RELATION_TYPES = frozenset(
    {
        "RELATED_TO",
        "DEPENDS_ON",
        "REFINES",
        "DEPRECATES",
        "CONFLICTS_WITH",
        "EVOLVES_FROM",
        "MERGED_INTO",
        "LEARNED_FROM",
        "IMPLEMENTS",
        "EVIDENCES",
        "MODIFIES",
    }
)


class LedgerModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    def model_copy(self, *, update: dict[str, Any] | None = None, deep: bool = False):  # noqa: ANN001
        """Copia validada de um modelo do ledger.

        ``BaseModel.model_copy(update=...)`` do Pydantic é deliberadamente rápido,
        mas não revalida o dicionário de atualização. Para modelos que representam
        o histórico canônico isso permitiria inserir timestamps ingênuos, payloads
        inválidos ou hashes inconsistentes após a construção inicial.
        """

        data = self.model_dump(mode="python")
        if update:
            data.update(update)
        if deep:
            data = json.loads(json.dumps(data, default=str))
        return type(self).model_validate(data)

    @model_validator(mode="after")
    def validate_utc_datetimes(self):  # noqa: ANN001
        for name, value in self.__dict__.items():
            if isinstance(value, datetime) and value.tzinfo is None:
                raise ValueError(f"{name} precisa conter timezone explícito")
        return self


def _tuple_text(value: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    return tuple(item.strip() for item in (value or ()) if str(item).strip())


class MemoryContent(LedgerModel):
    """Snapshot semântico completo; não contém estado derivado de ranking."""

    schema_version: str = "1"
    project: str
    category: str
    title: str
    summary: str
    details: str = ""
    objective: str = ""
    trigger: str = ""
    domain: tuple[str, ...] = ()
    modules: tuple[str, ...] = ()
    stakeholders: tuple[str, ...] = ()
    action_triggers: tuple[str, ...] = ()
    related_files: tuple[str, ...] = ()
    business_rules: tuple[str, ...] = ()
    architectural_rationale: str = ""
    examples: tuple[str, ...] = ()
    alternatives_considered: tuple[str, ...] = ()
    # Governança de peso também é versionada. ``None`` preserva compatibilidade
    # com snapshots antigos que ainda não tinham esse campo.
    weight_manual: float | None = Field(default=None, ge=0.0, le=1.0)
    weight_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    weight_usage: float = Field(default=0.0, ge=0.0, le=1.0)
    weight_feedback: float = Field(default=0.0, ge=0.0, le=1.0)
    weight_contextual: float = Field(default=0.5, ge=0.0, le=1.0)
    significance: float = Field(default=0.5, ge=0.0, le=1.0)
    last_accessed_at: datetime | None = None
    memory_scope: MemoryScope = MemoryScope.SEMANTIC
    memory_branch: str = "semantic"
    git_ref: str = ""
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    payload_schema: str | None = None
    structured_payload_json: str = ""
    legacy_ids: tuple[tuple[str, str], ...] = ()

    @model_validator(mode="before")
    @classmethod
    def normalize_structured_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        # ``structured_payload`` é a API amigável; o ledger armazena a forma
        # textual canônica para não deixar um dict mutável dentro de um modelo
        # frozen. A forma textual também é estável para content_hash.
        structured = data.pop("structured_payload", None)
        if structured is not None:
            if isinstance(structured, str):
                try:
                    structured = json.loads(structured)
                except json.JSONDecodeError as error:
                    raise ValueError("structured_payload precisa ser JSON válido") from error
            if not isinstance(structured, dict):
                raise ValueError("structured_payload precisa ser um objeto JSON")
            structured_json = canonical_json(structured)
            existing_json = data.get("structured_payload_json")
            if existing_json:
                if not isinstance(existing_json, str):
                    raise ValueError("structured_payload_json precisa ser texto JSON")
                try:
                    existing_json = canonical_json(json.loads(existing_json))
                except (json.JSONDecodeError, TypeError, ValueError) as error:
                    raise ValueError("structured_payload_json precisa ser JSON válido") from error
                if existing_json != structured_json:
                    raise ValueError(
                        "structured_payload e structured_payload_json não podem divergir"
                    )
            data["structured_payload_json"] = structured_json
        return data

    @field_validator(
        "project",
        "category",
        "title",
        "summary",
        "details",
        "objective",
        "trigger",
        "architectural_rationale",
        "memory_branch",
        "git_ref",
        mode="before",
    )
    @classmethod
    def strip_text(cls, value: str | None) -> str:
        return str(value or "").strip()

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
    def normalize_lists(cls, value: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
        return _tuple_text(value)

    @field_validator("legacy_ids", mode="before")
    @classmethod
    def normalize_legacy_ids(cls, value: Any) -> tuple[tuple[str, str], ...]:
        if value is None:
            return ()
        if isinstance(value, dict):
            value = value.items()
        result = []
        for key, item in value:
            key_text, item_text = str(key).strip(), str(item).strip()
            if key_text and item_text:
                result.append((key_text, item_text))
        return tuple(sorted(set(result)))

    @field_validator("payload_schema", mode="before")
    @classmethod
    def normalize_payload_schema(cls, value: str | None) -> str | None:
        value = str(value).strip() if value else None
        if value and (".v" not in value or value.endswith(".v")):
            raise ValueError("payload_schema precisa seguir o formato name.vN")
        if value and value not in KNOWN_PAYLOAD_SCHEMAS:
            raise ValueError(f"payload_schema não registrado: {value}")
        return value

    @field_validator("structured_payload_json", mode="before")
    @classmethod
    def normalize_payload_json(cls, value: str | None) -> str:
        if not value:
            return ""
        if not isinstance(value, str):
            raise ValueError("structured_payload_json precisa ser texto JSON")
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError("structured_payload_json precisa ser JSON válido") from error
        if not isinstance(parsed, dict):
            raise ValueError("structured_payload_json precisa conter um objeto JSON")
        return canonical_json(parsed)

    @field_validator("project", "category", "title", "summary")
    @classmethod
    def require_identity_text(cls, value: str) -> str:
        if not value:
            raise ValueError("project, category, title and summary are required")
        return value

    @model_validator(mode="after")
    def validate_validity_window(self) -> "MemoryContent":
        for name, value in (("valid_from", self.valid_from), ("valid_to", self.valid_to)):
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{name} precisa conter timezone explícito")
        if self.valid_from and self.valid_to and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be later than valid_from")
        expected_schema = {
            MemoryScope.EPISODIC: "episodic.v1",
            MemoryScope.PROCEDURAL: "procedural.v1",
            MemoryScope.PULL_REQUEST: "pull_request.v1",
        }.get(self.memory_scope)
        if expected_schema and self.payload_schema != expected_schema:
            raise ValueError(f"{self.memory_scope.value} exige payload_schema={expected_schema}")
        if bool(self.payload_schema) != bool(self.structured_payload_json):
            raise ValueError("payload_schema e structured_payload precisam existir juntos")
        return self

    @property
    def structured_payload(self) -> dict[str, Any] | None:
        """Retorna uma cópia desserializada do payload imutável."""

        return json.loads(self.structured_payload_json) if self.structured_payload_json else None


class MemoryFamily(LedgerModel):
    family_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project: str
    category: str
    memory_scope: MemoryScope = MemoryScope.SEMANTIC
    created_at: datetime = Field(default_factory=utc_now)
    created_by: str = "system"
    legacy_memory_id: str = ""
    migration_run_id: str | None = None
    state: FamilyState = FamilyState.ACTIVE
    merged_into_family_id: uuid.UUID | None = None
    retired_at: datetime | None = None
    retirement_reason: str = ""


class MemoryRevision(LedgerModel):
    revision_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    family_id: uuid.UUID
    version: int = Field(ge=1)
    parent_revision_ids: tuple[uuid.UUID, ...] = ()
    content: MemoryContent
    content_hash: str
    actor_id: str
    actor_type: str = "operator"
    reason: str
    created_at: datetime = Field(default_factory=utc_now)
    recorded_from: datetime = Field(default_factory=utc_now)
    recorded_to: datetime | None = None
    evidence_ids: tuple[uuid.UUID, ...] = ()
    source_revision_ids: tuple[uuid.UUID, ...] = ()
    rollback_of: uuid.UUID | None = None
    schema_version: str = "1"
    field_origins: tuple["FieldOrigin", ...] = ()
    evidence_link_ids: tuple[uuid.UUID, ...] = ()
    conflict_ids: tuple[str, ...] = ()
    provenance_hash: str | None = None
    provenance_schema: str = "provenance.v1"
    merge_manifest_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_content_hash(self) -> "MemoryRevision":
        expected = content_hash(self.content)
        if self.content_hash != expected:
            raise ValueError("content_hash does not match the immutable content snapshot")
        if self.schema_version != self.content.schema_version:
            raise ValueError("revision and content schema versions must match")
        if any(origin.source_revision_id not in set(self.source_revision_ids) for origin in self.field_origins):
            raise ValueError("field origins precisam referenciar source revisions da revisão")
        if self.provenance_hash is not None:
            digest = self.provenance_hash.removeprefix("sha256:")
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()):
                raise ValueError("provenance_hash precisa ser um sha256 hexadecimal")
        return self


class MemoryHead(LedgerModel):
    family_id: uuid.UUID
    memory_scope: MemoryScope
    memory_branch: str
    revision_id: uuid.UUID
    sequence: int = Field(ge=1)
    updated_at: datetime = Field(default_factory=utc_now)


class MemoryRevisionView(LedgerModel):
    revision: MemoryRevision
    state: RevisionState
    is_current_head: bool
    invalidation_reason: str = ""
    transition_ids: tuple[uuid.UUID, ...] = ()


class MemoryAlias(LedgerModel):
    alias: str
    family_id: uuid.UUID | None = None
    project: str = ""
    category: str = ""
    memory_branch: str = "semantic"
    status: MemoryAliasStatus = MemoryAliasStatus.RESOLVED
    candidates: tuple[uuid.UUID, ...] = ()


class Evidence(LedgerModel):
    evidence_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    source_kind: str
    source_locator: str
    source_hash: str = ""
    captured_at: datetime = Field(default_factory=utc_now)
    observed_at: datetime | None = None
    author: str = ""
    extractor: str = ""
    model: str = ""
    model_version: str = ""
    source_reliability: float = Field(default=0.5, ge=0.0, le=1.0)
    verification: EvidenceVerification = EvidenceVerification.UNVERIFIED
    excerpt_or_hash: str = ""
    metadata: tuple[tuple[str, str], ...] = ()

    @property
    def fingerprint(self) -> str:
        # Identidade técnica e timestamps não fazem parte do conteúdo da fonte.
        # Excluí-los permite comparar a mesma evidência capturada em momentos
        # diferentes sem transformar cada captura em um conteúdo distinto.
        payload = self.model_dump(
            mode="json",
            exclude={"evidence_id", "captured_at", "observed_at"},
        )
        return "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

    @field_validator("source_kind", "source_locator", "source_hash", "author", "extractor", "model", "model_version", "excerpt_or_hash", mode="before")
    @classmethod
    def normalize_evidence_text(cls, value: str | None) -> str:
        return str(value or "").strip()


class RevisionEvidence(LedgerModel):
    link_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    revision_id: uuid.UUID
    evidence_id: uuid.UUID
    stance: EvidenceStance
    confidence: float = Field(ge=0.0, le=1.0)
    claim_path: str = ""
    excerpt_hash: str = ""


class EvidenceLinkSpec(LedgerModel):
    evidence_id: uuid.UUID
    stance: EvidenceStance = EvidenceStance.SUPPORTS
    confidence: float = Field(ge=0.0, le=1.0)
    claim_path: str = ""
    excerpt_hash: str = ""

    @model_validator(mode="after")
    def validate_link_claim(self) -> "EvidenceLinkSpec":
        if not self.claim_path.strip() and self.excerpt_hash.strip():
            raise ValueError("excerpt_hash sem claim_path não identifica um claim")
        return self


class ConflictMember(LedgerModel):
    revision_id: uuid.UUID
    family_id: uuid.UUID
    claim_path: str
    normalized_value_hash: str
    evidence_ids: tuple[uuid.UUID, ...] = ()


class ConflictCase(LedgerModel):
    conflict_id: str
    claim_key: str
    claim_path: str
    memory_scope: MemoryScope
    memory_branch: str
    status: ConflictStatus = ConflictStatus.OPEN
    version: int = Field(default=1, ge=1)
    detector_version: str = "merge-detector.v1"
    coverage: ConflictDetectionCoverage
    members: tuple[ConflictMember, ...]
    snapshot_hash: str


class ConflictResolution(LedgerModel):
    resolution_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    conflict_id: str
    expected_conflict_version: int = Field(ge=1)
    claim_path: str
    decision: str
    chosen_value_hash: str | None = None
    synthesized_value_json: str | None = None
    field_origins: tuple["FieldOrigin", ...] = ()
    evidence_link_ids: tuple[uuid.UUID, ...] = ()
    reason: str

    @model_validator(mode="after")
    def validate_resolution_shape(self) -> "ConflictResolution":
        if not self.claim_path.strip():
            raise ValueError("claim_path é obrigatório na resolução do conflito")
        if not self.decision.strip():
            raise ValueError("decision é obrigatório na resolução do conflito")
        if not self.reason.strip():
            raise ValueError("reason é obrigatório na resolução do conflito")
        if self.chosen_value_hash is None and self.synthesized_value_json is None:
            raise ValueError("a resolução precisa escolher um valor ou sintetizar um valor")
        if self.synthesized_value_json is not None:
            try:
                parsed = json.loads(self.synthesized_value_json)
            except json.JSONDecodeError as error:
                raise ValueError("synthesized_value_json precisa ser JSON válido") from error
            canonical_json(parsed)
        return self


class MergeHeadSnapshot(LedgerModel):
    family_id: uuid.UUID
    memory_scope: MemoryScope
    memory_branch: str
    revision_id: uuid.UUID
    sequence: int = Field(ge=1)


class MergeManifest(LedgerModel):
    manifest_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    manifest_schema: str = "merge-manifest.v1"
    merge_revision_id: uuid.UUID
    target_family_id: uuid.UUID
    source_family_ids: tuple[uuid.UUID, ...]
    previous_heads: tuple[MergeHeadSnapshot, ...]
    previous_family_snapshots: tuple["MemoryFamily", ...]
    aliases_before: tuple["MemoryAlias", ...] = ()
    affected_relation_snapshots: tuple["RelationAssertion", ...] = ()
    created_relation_ids: tuple[uuid.UUID, ...] = ()
    field_origins: tuple[FieldOrigin, ...] = ()
    proposal_id: uuid.UUID
    approval_id: uuid.UUID
    manifest_hash: str

    @model_validator(mode="after")
    def validate_manifest_hash(self) -> "MergeManifest":
        if self.target_family_id in self.source_family_ids:
            raise ValueError("a família alvo não pode aparecer nas famílias de origem")
        if not any(item.family_id == self.target_family_id for item in self.previous_heads):
            raise ValueError("manifesto precisa capturar o head da família alvo")
        payload = self.model_dump(mode="json", exclude={"manifest_hash"})
        expected = "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        if self.manifest_hash != expected:
            raise ValueError("manifest_hash não corresponde ao conteúdo do manifesto")
        return self


class UsageObservation(LedgerModel):
    observation_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    procedure_family_id: uuid.UUID
    procedure_revision_id: uuid.UUID
    success: bool
    observed_at: datetime = Field(default_factory=utc_now)
    recorded_at: datetime = Field(default_factory=utc_now)
    correlation_id: str
    idempotency_key: str
    actor_id: str = "system"
    result: str = ""
    payload_hash: str

    @field_validator("observed_at", "recorded_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps precisam conter timezone explícito")
        return value


class FieldDiff(LedgerModel):
    field: str
    before: Any = None
    after: Any = None


class FieldOrigin(LedgerModel):
    field: str
    source_revision_id: uuid.UUID
    note: str = ""


class ChangeProposal(LedgerModel):
    proposal_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    operation: LedgerOperation
    target_family_id: uuid.UUID | None = None
    target_branch: str = "semantic"
    base_revision_ids: tuple[uuid.UUID, ...] = ()
    expected_heads: tuple[tuple[uuid.UUID, str, str, uuid.UUID], ...] = ()
    source_revision_ids: tuple[uuid.UUID, ...] = ()
    before: tuple[MemoryContent, ...] = ()
    after: MemoryContent | None = None
    field_diff: tuple[FieldDiff, ...] = ()
    field_origins: tuple[FieldOrigin, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    evidence_ids: tuple[uuid.UUID, ...] = ()
    evidence_links: tuple[EvidenceLinkSpec, ...] = ()
    conflict_ids: tuple[str, ...] = ()
    conflict_snapshot_hash: str = ""
    conflict_versions: tuple[tuple[str, int], ...] = ()
    detector_version: str | None = None
    detector_coverage: ConflictDetectionCoverage | None = None
    conflicts: tuple[ConflictCase, ...] = ()
    conflict_resolutions: tuple[ConflictResolution, ...] = ()
    reason: str
    requested_by: str
    requested_by_type: str = "agent"
    risk_level: str = "medium"
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime | None = None
    preview_hash: str
    status: ProposalStatus = ProposalStatus.PENDING_APPROVAL
    applied_revision_id: uuid.UUID | None = None
    applied_relation_id: uuid.UUID | None = None
    idempotency_key: str = ""
    rejected_by: str = ""
    rejected_by_type: str = ""
    rejected_at: datetime | None = None
    restore_revision_id: uuid.UUID | None = None
    relation_type: str = ""
    relation_target_family_id: uuid.UUID | None = None
    replacement_family_id: uuid.UUID | None = None
    replacement_alias: str = ""
    merge_manifest_id: uuid.UUID | None = None
    expected_manifest_hash: str = ""

    @model_validator(mode="after")
    def validate_operation_contract(self) -> "ChangeProposal":
        content_operations = {
            LedgerOperation.CREATE,
            LedgerOperation.CREATE_AND_LINK,
            LedgerOperation.UPDATE,
            LedgerOperation.MERGE,
            LedgerOperation.INVALIDATE,
            LedgerOperation.SUPERSEDE,
            LedgerOperation.ARCHIVE,
            LedgerOperation.ROLLBACK,
            LedgerOperation.RESOLVE_CONFLICT,
        }
        if self.operation in content_operations and self.after is None:
            raise ValueError(f"{self.operation.value} proposals require an after snapshot")
        if self.operation is LedgerOperation.UNMERGE:
            if self.after is not None:
                raise ValueError("unmerge não recebe snapshot de conteúdo")
            if self.target_family_id is None or self.merge_manifest_id is None:
                raise ValueError("unmerge requer família e manifesto")
            if not self.expected_manifest_hash:
                raise ValueError("unmerge requer CAS do manifesto")
        if self.operation is LedgerOperation.CREATE:
            if self.target_family_id is not None or self.before:
                raise ValueError("create proposals cannot target an existing family")
        elif self.operation is LedgerOperation.CREATE_AND_LINK:
            if self.target_family_id is not None or self.before:
                raise ValueError("create_and_link proposals cannot target an existing source family")
            if self.relation_target_family_id is None:
                raise ValueError("create_and_link proposals require a relation target family")
        elif self.operation in content_operations and self.target_family_id is None:
            raise ValueError(f"{self.operation.value} proposals require a target family")
        if self.operation is LedgerOperation.MERGE and len(self.source_revision_ids) < 2:
            raise ValueError("merge proposals require at least two source revisions")
        if self.operation is LedgerOperation.RESOLVE_CONFLICT and not self.conflict_resolutions:
            raise ValueError("resolve_conflict proposals require at least one resolution")
        if len(set(self.source_revision_ids)) != len(self.source_revision_ids):
            raise ValueError("source revisions must be unique")
        if len(set(self.base_revision_ids)) != len(self.base_revision_ids):
            raise ValueError("base revisions must be unique")
        if self.operation in {
            LedgerOperation.UPDATE,
            LedgerOperation.CREATE_AND_LINK,
            LedgerOperation.MERGE,
            LedgerOperation.INVALIDATE,
            LedgerOperation.SUPERSEDE,
            LedgerOperation.ARCHIVE,
            LedgerOperation.ROLLBACK,
            LedgerOperation.RESOLVE_CONFLICT,
        } and not self.expected_heads:
            raise ValueError(f"{self.operation.value} proposals require compare-and-swap heads")
        if self.evidence_ids != tuple(item.evidence_id for item in self.evidence):
            raise ValueError("evidence_ids must match the embedded evidence records")
        evidence_ids = {item.evidence_id for item in self.evidence}
        if len(evidence_ids) != len(self.evidence):
            raise ValueError("evidence não pode conter o mesmo evidence_id duas vezes")
        if any(item.evidence_id not in evidence_ids for item in self.evidence_links):
            raise ValueError("evidence links precisam referenciar evidências embutidas")
        link_keys = {
            (item.evidence_id, item.stance, item.claim_path, item.excerpt_hash)
            for item in self.evidence_links
        }
        if len(link_keys) != len(self.evidence_links):
            raise ValueError("evidence links duplicados não são permitidos")
        source_ids = set(self.source_revision_ids)
        if any(origin.source_revision_id not in source_ids for origin in self.field_origins):
            raise ValueError("field origins must reference a source revision")
        if self.operation in {LedgerOperation.LINK, LedgerOperation.CREATE_AND_LINK}:
            if self.operation is LedgerOperation.LINK and (
                not self.target_family_id or not self.relation_target_family_id
            ):
                raise ValueError("link proposals require source and target families")
            if self.operation is LedgerOperation.CREATE_AND_LINK and not self.relation_target_family_id:
                raise ValueError("create_and_link proposals require a target family")
            if self.relation_type.strip().upper() not in KNOWN_RELATION_TYPES:
                raise ValueError(f"relation type não registrado: {self.relation_type}")
            if not self.expected_heads:
                raise ValueError("relation proposals require compare-and-swap heads")
        if not self.requested_by.strip():
            raise ValueError("requested_by is required")
        if not self.preview_hash.strip():
            raise ValueError("preview_hash is required")
        return self


class ApprovalDecision(LedgerModel):
    approval_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    proposal_id: uuid.UUID
    principal_id: str
    principal_type: str = "operator"
    preview_hash: str
    expected_heads: tuple[tuple[uuid.UUID, str, str, uuid.UUID], ...] = ()
    comment: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime | None = None
    consumed_at: datetime | None = None
    status: ApprovalStatus = ApprovalStatus.ISSUED

    @model_validator(mode="after")
    def validate_operator(self) -> "ApprovalDecision":
        if not self.principal_id.strip():
            raise ValueError("principal_id is required")
        if self.principal_id.strip().casefold().startswith(("agent", "system", "anonymous")):
            raise ValueError("approval requires a trusted human/operator principal")
        if self.principal_type.strip().lower() in {"agent", "system", "anonymous"}:
            raise ValueError("approval requires an operator principal")
        if not self.preview_hash.strip():
            raise ValueError("preview_hash is required")
        return self


class RevisionTransition(LedgerModel):
    transition_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    family_id: uuid.UUID
    from_revision_ids: tuple[uuid.UUID, ...] = ()
    to_revision_id: uuid.UUID | None = None
    state: RevisionState
    reason: str
    actor_id: str
    actor_type: str = "operator"
    created_at: datetime = Field(default_factory=utc_now)
    proposal_id: uuid.UUID | None = None


class OutboxEvent(LedgerModel):
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: str
    family_id: uuid.UUID
    revision_id: uuid.UUID | None = None
    content_hash: str
    sequence: int = Field(ge=1)
    payload: tuple[tuple[str, str], ...] = ()
    status: OutboxStatus = OutboxStatus.PENDING
    attempts: int = 0
    available_at: datetime = Field(default_factory=utc_now)
    lease_until: datetime | None = None
    claimed_by: str | None = None
    claim_token: str | None = None
    last_error: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class RelationAssertion(LedgerModel):
    assertion_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    source_family_id: uuid.UUID
    target_family_id: uuid.UUID
    source_revision_id: uuid.UUID | None = None
    target_revision_id: uuid.UUID | None = None
    relation_type: str
    memory_scope: MemoryScope = MemoryScope.SEMANTIC
    memory_branch: str = "semantic"
    evidence_ids: tuple[uuid.UUID, ...] = ()
    rationale: str = ""
    created_by: str
    created_at: datetime = Field(default_factory=utc_now)
    state: RelationState = RelationState.ACTIVE
    proposal_id: uuid.UUID | None = None

    @field_validator("relation_type", mode="before")
    @classmethod
    def normalize_relation_type(cls, value: str | None) -> str:
        normalized = str(value or "").strip().upper()
        if normalized not in KNOWN_RELATION_TYPES:
            raise ValueError(f"relation type não registrado: {normalized or '<empty>'}")
        return normalized

    @model_validator(mode="after")
    def validate_relation(self) -> "RelationAssertion":
        if self.source_family_id == self.target_family_id:
            raise ValueError("a relation cannot connect a family to itself")
        if not self.relation_type.strip():
            raise ValueError("relation_type is required")
        return self
