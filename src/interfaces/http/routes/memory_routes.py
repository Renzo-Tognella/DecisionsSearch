from __future__ import annotations

import logging
import uuid
from typing import Any, TypeVar

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ValidationError

from decisionssearch.domain import (
    AdmissionError,
    CatalogConflictError,
    CatalogNotFoundError,
    CatalogValidationError,
    CreateManualMemoryCommand,
    ApprovalError,
    LedgerConflictError,
    MemoryServiceError,
)
from decisionssearch.application.memory.ledger.operator_identity import TrustedOperatorResolver
from decisionssearch.application.memory.project_context import resolve_project
from decisionssearch.interfaces.http.schemas.schemas import (
    ManualMemoryCreateRequest,
    ManualMemoryResponse,
    MemoryChangeApprovalRequest,
    MemoryChangeApplyRequest,
    MemoryChangeRejectionRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/memories", tags=["memories"])

_CommandT = TypeVar("_CommandT")


def _container(request: Request) -> Any:
    return request.app.state.container


def _build_command(command_cls: type[_CommandT], payload: BaseModel) -> _CommandT:
    try:
        payload_data = payload.model_dump()
        if "project" in payload_data:
            payload_data["project"] = resolve_project(payload_data.get("project"))
        return command_cls(**payload_data)
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=jsonable_encoder(error.errors()),
        ) from error


def _resolve_operator(
    operator_id: str | None,
    operator_token: str | None,
) -> str:
    try:
        return TrustedOperatorResolver.from_env().resolve(operator_id, operator_token)
    except ApprovalError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error


def _memory_http_error(error: Exception) -> HTTPException:
    logger.error("Memory error: %s", error, exc_info=True)
    if isinstance(error, AdmissionError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=jsonable_encoder({
                "message": str(error),
                "gate": error.gate,
                "candidate_title": error.candidate_title,
                "context": error.context,
            }),
        )
    if isinstance(error, CatalogNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=jsonable_encoder({
                "message": str(error),
                "resource": error.resource,
                "identifier": error.identifier,
                "context": error.context,
            }),
        )
    if isinstance(error, CatalogConflictError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=jsonable_encoder({
                "message": str(error),
                "resource": error.resource,
                "identifier": error.identifier,
                "context": error.context,
            }),
        )
    if isinstance(error, CatalogValidationError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=jsonable_encoder({
                "message": str(error),
                "field": error.field,
                "value": error.value,
                "context": error.context,
            }),
        )
    if isinstance(error, MemoryServiceError):
        if isinstance(error, LedgerConflictError):
            return HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=jsonable_encoder({"message": str(error), "context": error.context}),
            )
        if isinstance(error, ApprovalError):
            return HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=jsonable_encoder({"message": str(error), "context": error.context}),
            )
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=jsonable_encoder({"message": str(error), "context": error.context}),
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=jsonable_encoder({"message": str(error)}),
    )


@router.post("/manual", response_model=ManualMemoryResponse)
async def create_manual_memory(
    payload: ManualMemoryCreateRequest,
    request: Request,
    response: Response,
) -> ManualMemoryResponse:
    try:
        command = _build_command(CreateManualMemoryCommand, payload)
        result = await _container(request).manual_memory_authoring.create_manual_memory(command)
        if isinstance(result, dict) and result.get("proposal_id"):
            response.status_code = status.HTTP_202_ACCEPTED
    except HTTPException:
        raise
    except Exception as error:
        raise _memory_http_error(error) from error
    return ManualMemoryResponse.model_validate(result)


@router.get("/changes/{proposal_id}")
async def get_memory_change(proposal_id: str, request: Request) -> dict:
    """Retorna o preview server-side sem aplicar a alteração."""
    try:
        proposal = await _container(request).ledger.get_proposal(uuid.UUID(proposal_id))
        return proposal.model_dump(mode="json")
    except Exception as error:
        raise _memory_http_error(error) from error


@router.post("/changes/{proposal_id}/approve")
async def approve_memory_change(
    proposal_id: str,
    payload: MemoryChangeApprovalRequest,
    request: Request,
    x_operator_id: str | None = Header(default=None),
    x_operator_token: str | None = Header(default=None),
) -> dict:
    """Aprovação local em superfície do operador, fora das tools do agente."""
    operator_id = _resolve_operator(x_operator_id, x_operator_token)
    try:
        approval = await _container(request).approval_boundary.approve(
            uuid.UUID(proposal_id),
            principal_id=operator_id,
            principal_type="operator",
            preview_hash=payload.preview_hash,
            comment=payload.comment,
        )
        return approval.model_dump(mode="json")
    except Exception as error:
        raise _memory_http_error(error) from error


@router.post("/changes/{proposal_id}/reject")
async def reject_memory_change(
    proposal_id: str,
    payload: MemoryChangeRejectionRequest,
    request: Request,
    x_operator_id: str | None = Header(default=None),
    x_operator_token: str | None = Header(default=None),
) -> dict:
    operator_id = _resolve_operator(x_operator_id, x_operator_token)
    try:
        proposal = await _container(request).approval_boundary.reject(
            uuid.UUID(proposal_id),
            payload.reason,
            principal_id=operator_id,
        )
        return proposal.model_dump(mode="json")
    except Exception as error:
        raise _memory_http_error(error) from error


@router.post("/changes/{proposal_id}/apply")
async def apply_memory_change(
    proposal_id: str,
    payload: MemoryChangeApplyRequest,
    request: Request,
    x_operator_id: str | None = Header(default=None),
    x_operator_token: str | None = Header(default=None),
) -> dict:
    operator_id = _resolve_operator(x_operator_id, x_operator_token)
    try:
        approval = await _container(request).ledger.get_approval(uuid.UUID(payload.approval_id))
        if approval is None or approval.proposal_id != uuid.UUID(proposal_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Aprovação não encontrada")
        if approval.principal_id != operator_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Somente o operador que aprovou pode aplicar esta proposta",
            )
        result = await _container(request).ledger_apply.apply(
            uuid.UUID(proposal_id), uuid.UUID(payload.approval_id)
        )
        proposal = await _container(request).ledger.get_proposal(uuid.UUID(proposal_id))
        result_payload = result.model_dump(mode="json")
        legacy_id = ""
        if proposal.after is not None:
            legacy_id = dict(proposal.after.legacy_ids).get("memory_id", "")
        return {
            **result_payload,
            "status": "applied",
            "proposal_id": proposal_id,
            "approval_id": payload.approval_id,
            "preview_hash": proposal.preview_hash,
            "memory_id": legacy_id or result_payload.get("memory_id"),
            "result": result_payload,
        }
    except HTTPException:
        raise
    except Exception as error:
        raise _memory_http_error(error) from error
