from __future__ import annotations

import logging
from typing import Any, TypeVar

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ValidationError

from decisionssearch.domain import (
    CatalogConflictError,
    CatalogImportError,
    CatalogNotFoundError,
    CatalogValidationError,
    CreateCategoryCommand,
    CreateDomainCommand,
    CreateProjectCommand,
    CreateRelationCommand,
    DeleteRelationCommand,
    MemoryServiceError,
    UpdateProjectCommand,
)
from decisionssearch.interfaces.http.schemas.schemas import (
    CatalogCategoryCreateRequest,
    CatalogCsvBundleResponse,
    CatalogCsvImportRequest,
    CatalogCsvImportResponse,
    CatalogDomainCreateRequest,
    CatalogNodeResponse,
    CatalogProjectCreateRequest,
    CatalogProjectUpdateRequest,
    CatalogRelationCreateRequest,
    CatalogRelationDeleteRequest,
    OperationStatusResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/catalog", tags=["catalog"])

_CommandT = TypeVar("_CommandT")


def _container(request: Request) -> Any:
    return request.app.state.container


def _build_command(command_cls: type[_CommandT], payload: BaseModel, **extra: Any) -> _CommandT:
    data = payload.model_dump()
    data.update(extra)
    try:
        return command_cls(**data)
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=jsonable_encoder(error.errors()),
        ) from error


def _structured_error(
    *,
    status_code: int,
    error_code: str,
    message: str,
    operation: str,
    resource: str,
    context: dict[str, Any] | None = None,
    **extra: Any,
) -> HTTPException:
    payload = {
        "error": error_code,
        "message": message,
        "operation": operation,
        "resource": resource,
        "context": context or {},
    }
    payload.update(extra)
    return HTTPException(status_code=status_code, detail=jsonable_encoder(payload))


def _catalog_memory_error(
    error: MemoryServiceError, *, operation: str, resource: str,
) -> HTTPException:
    message = str(error).lower()
    context = error.context

    if "falha ao listar" in message:
        return _structured_error(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code="catalog_unavailable",
            message=str(error),
            operation=operation,
            resource=resource,
            context=context,
        )

    if "projeto pai nao encontrado" in message:
        return _structured_error(
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="catalog_project_not_found",
            message=str(error),
            operation=operation,
            resource=resource,
            context=context,
        )

    if "tipo de no catalogo invalido" in message:
        return _structured_error(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            error_code="catalog_invalid_kind",
            message=str(error),
            operation=operation,
            resource=resource,
            context=context,
        )

    if "relacao invalida para catalogo" in message:
        return _structured_error(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            error_code="catalog_invalid_relation_type",
            message=str(error),
            operation=operation,
            resource=resource,
            context=context,
        )

    if "nao encontrada para remocao" in message:
        return _structured_error(
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="catalog_relation_not_found",
            message=str(error),
            operation=operation,
            resource=resource,
            context=context,
        )

    if "nao pode ser criada sem origem e destino validos" in message:
        return _structured_error(
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="catalog_relation_endpoint_not_found",
            message=str(error),
            operation=operation,
            resource=resource,
            context=context,
        )

    if "nao pode ser removido com relacoes inseguras" in message:
        return _structured_error(
            status_code=status.HTTP_409_CONFLICT,
            error_code="catalog_delete_blocked",
            message=str(error),
            operation=operation,
            resource=resource,
            context=context,
        )

    return _structured_error(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        error_code="catalog_service_error",
        message=str(error),
        operation=operation,
        resource=resource,
        context=context,
    )


def _catalog_http_error(error: Exception, *, operation: str, resource: str) -> HTTPException:
    logger.error("Catalog error [%s/%s]: %s", operation, resource, error, exc_info=True)
    if isinstance(error, CatalogNotFoundError):
        return _structured_error(
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="catalog_not_found",
            message=str(error),
            operation=operation,
            resource=resource,
            context=error.context,
            identifier=error.identifier or None,
            catalog_resource=error.resource or None,
        )
    if isinstance(error, CatalogConflictError):
        return _structured_error(
            status_code=status.HTTP_409_CONFLICT,
            error_code="catalog_conflict",
            message=str(error),
            operation=operation,
            resource=resource,
            context=error.context,
            identifier=error.identifier or None,
            catalog_resource=error.resource or None,
        )
    if isinstance(error, CatalogValidationError):
        return _structured_error(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            error_code="catalog_validation_error",
            message=str(error),
            operation=operation,
            resource=resource,
            context=error.context,
            field=error.field or None,
            value=error.value,
        )
    if isinstance(error, CatalogImportError):
        return _structured_error(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            error_code="catalog_import_error",
            message=str(error),
            operation=operation,
            resource=resource,
            context=error.context,
            source=error.source or None,
            row=error.row,
        )
    if isinstance(error, MemoryServiceError):
        return _catalog_memory_error(error, operation=operation, resource=resource)
    return _structured_error(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        error_code="catalog_service_error",
        message=str(error),
        operation=operation,
        resource=resource,
    )


def _to_node_response(item: dict[str, Any]) -> CatalogNodeResponse:
    return CatalogNodeResponse.model_validate(item)


@router.get("/export/csv", response_model=CatalogCsvBundleResponse)
async def export_catalog_csv(request: Request) -> CatalogCsvBundleResponse:
    try:
        result = await _container(request).catalog_csv.export_catalog_csv_bundle()
    except HTTPException:
        raise
    except Exception as error:
        raise _catalog_http_error(
            error, operation="export_catalog_csv", resource="catalog_csv",
        ) from error
    return CatalogCsvBundleResponse.model_validate(result)


@router.post("/import/csv", response_model=CatalogCsvImportResponse)
async def import_catalog_csv(
    payload: CatalogCsvImportRequest,
    request: Request,
) -> CatalogCsvImportResponse:
    try:
        result = await _container(request).catalog_csv.import_catalog_csv_bundle(
            payload.model_dump(),
        )
    except HTTPException:
        raise
    except Exception as error:
        raise _catalog_http_error(
            error, operation="import_catalog_csv", resource="catalog_csv",
        ) from error
    return CatalogCsvImportResponse.model_validate(result)


@router.get("/projects", response_model=list[CatalogNodeResponse])
async def list_projects(request: Request) -> list[CatalogNodeResponse]:
    try:
        items = await _container(request).graph_catalog.list_projects()
    except HTTPException:
        raise
    except Exception as error:
        raise _catalog_http_error(error, operation="list_projects", resource="project") from error
    return [_to_node_response(item) for item in items]


@router.post("/projects", response_model=CatalogNodeResponse)
async def create_project(
    payload: CatalogProjectCreateRequest,
    request: Request,
) -> CatalogNodeResponse:
    try:
        command = _build_command(CreateProjectCommand, payload)
        result = await _container(request).graph_catalog.create_project(command)
    except HTTPException:
        raise
    except Exception as error:
        raise _catalog_http_error(error, operation="create_project", resource="project") from error
    return _to_node_response(result)


@router.patch("/projects/{project_id}", response_model=CatalogNodeResponse)
async def update_project(
    project_id: str,
    payload: CatalogProjectUpdateRequest,
    request: Request,
) -> CatalogNodeResponse:
    try:
        command = _build_command(UpdateProjectCommand, payload, id=project_id)
        result = await _container(request).graph_catalog.update_project(command)
    except HTTPException:
        raise
    except Exception as error:
        raise _catalog_http_error(error, operation="update_project", resource="project") from error
    return _to_node_response(result)


@router.get("/categories", response_model=list[CatalogNodeResponse])
async def list_categories(request: Request) -> list[CatalogNodeResponse]:
    try:
        items = await _container(request).graph_catalog.list_categories()
    except HTTPException:
        raise
    except Exception as error:
        raise _catalog_http_error(
            error, operation="list_categories", resource="category",
        ) from error
    return [_to_node_response(item) for item in items]


@router.post("/categories", response_model=CatalogNodeResponse)
async def create_category(
    payload: CatalogCategoryCreateRequest,
    request: Request,
) -> CatalogNodeResponse:
    try:
        command = _build_command(CreateCategoryCommand, payload)
        result = await _container(request).graph_catalog.create_category(command)
    except HTTPException:
        raise
    except Exception as error:
        raise _catalog_http_error(
            error, operation="create_category", resource="category",
        ) from error
    return _to_node_response(result)


@router.get("/domains", response_model=list[CatalogNodeResponse])
async def list_domains(request: Request) -> list[CatalogNodeResponse]:
    try:
        items = await _container(request).graph_catalog.list_domains()
    except HTTPException:
        raise
    except Exception as error:
        raise _catalog_http_error(error, operation="list_domains", resource="domain") from error
    return [_to_node_response(item) for item in items]


@router.post("/domains", response_model=CatalogNodeResponse)
async def create_domain(
    payload: CatalogDomainCreateRequest,
    request: Request,
) -> CatalogNodeResponse:
    try:
        command = _build_command(CreateDomainCommand, payload)
        result = await _container(request).graph_catalog.create_domain(command)
    except HTTPException:
        raise
    except Exception as error:
        raise _catalog_http_error(error, operation="create_domain", resource="domain") from error
    return _to_node_response(result)


@router.post("/relations", response_model=OperationStatusResponse)
async def create_relation(
    payload: CatalogRelationCreateRequest,
    request: Request,
) -> OperationStatusResponse:
    try:
        command = _build_command(CreateRelationCommand, payload)
        await _container(request).graph_operations.create_relation(command)
    except HTTPException:
        raise
    except Exception as error:
        raise _catalog_http_error(
            error, operation="create_relation", resource="relation",
        ) from error
    return OperationStatusResponse()


@router.delete("/relations", response_model=OperationStatusResponse)
async def delete_relation(
    payload: CatalogRelationDeleteRequest,
    request: Request,
) -> OperationStatusResponse:
    try:
        command = _build_command(DeleteRelationCommand, payload)
        await _container(request).graph_operations.delete_relation(command)
    except HTTPException:
        raise
    except Exception as error:
        raise _catalog_http_error(
            error, operation="delete_relation", resource="relation",
        ) from error
    return OperationStatusResponse()
