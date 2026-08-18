"""Hierarquia de exceções custom para o sistema de memória."""

from __future__ import annotations


class MemoryServiceError(Exception):
    """Base para todos os erros do sistema de memória."""

    def __init__(self, message: str, context: dict | None = None):
        self.context = context or {}
        super().__init__(message)


class StorageConsistencyError(MemoryServiceError):
    """Divergência entre Neo4j e Qdrant."""

    def __init__(
        self,
        message: str,
        memory_id: str,
        store: str,
        context: dict | None = None,
    ):
        self.memory_id = memory_id
        self.store = store
        super().__init__(message, context)


class LedgerConflictError(MemoryServiceError):
    """A proposta aponta para heads que já foram alterados."""


class ApprovalError(MemoryServiceError):
    """A decisão não pode ser emitida, consumida ou reutilizada."""


class ProposalNotFoundError(MemoryServiceError):
    """A proposta solicitada não existe no ledger."""


class AdmissionError(MemoryServiceError):
    """Erro durante avaliação nos gates de admissão."""

    def __init__(
        self,
        message: str,
        gate: str,
        candidate_title: str = "",
        context: dict | None = None,
    ):
        self.gate = gate
        self.candidate_title = candidate_title
        super().__init__(message, context)


class ExtractionError(MemoryServiceError):
    """Erro na extração estruturada via LLM."""

    def __init__(
        self,
        message: str,
        model: str = "",
        retries_exhausted: bool = False,
        context: dict | None = None,
    ):
        self.model = model
        self.retries_exhausted = retries_exhausted
        super().__init__(message, context)


class EmbeddingError(MemoryServiceError):
    """Erro ao gerar embedding."""

    def __init__(self, message: str, provider: str = "", context: dict | None = None):
        self.provider = provider
        super().__init__(message, context)


class SanitizationError(MemoryServiceError):
    """Erro durante sanitização."""

    def __init__(self, message: str, reason: str = "", context: dict | None = None):
        self.reason = reason
        super().__init__(message, context)


class BootstrapError(MemoryServiceError):
    """Erro durante bootstrap do universo semântico."""


class CatalogValidationError(MemoryServiceError):
    """Erro de validação ao montar ou alterar contratos do catalogo."""

    def __init__(
        self,
        message: str,
        field: str = "",
        value: object | None = None,
        context: dict | None = None,
    ):
        self.field = field
        self.value = value
        super().__init__(message, context)


class CatalogConflictError(MemoryServiceError):
    """Conflito de unicidade ou estado ao operar o catalogo."""

    def __init__(
        self,
        message: str,
        resource: str = "",
        identifier: str = "",
        context: dict | None = None,
    ):
        self.resource = resource
        self.identifier = identifier
        super().__init__(message, context)


class CatalogNotFoundError(MemoryServiceError):
    """Recurso do catalogo nao encontrado."""

    def __init__(
        self,
        message: str,
        resource: str = "",
        identifier: str = "",
        context: dict | None = None,
    ):
        self.resource = resource
        self.identifier = identifier
        super().__init__(message, context)


class CatalogImportError(MemoryServiceError):
    """Falha ao importar dados do catalogo."""

    def __init__(
        self,
        message: str,
        source: str = "",
        row: int | None = None,
        context: dict | None = None,
    ):
        self.source = source
        self.row = row
        super().__init__(message, context)
