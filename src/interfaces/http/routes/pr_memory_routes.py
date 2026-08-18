from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from decisionssearch.domain import CreatePRMemoryCommand, MemoryServiceError
from decisionssearch.application.memory.project_context import resolve_project
from decisionssearch.interfaces.http.schemas.schemas import PRMemoryCreateRequest, PRMemoryResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pr-memories", tags=["pr-memories"])


def _container(request: Request) -> Any:
    return request.app.state.container


def _structured_error(
    message: str,
    *,
    operation: str,
    resource: str,
    context: dict | None = None,
) -> HTTPException:
    logger.error(
        "PR memory error [%s/%s]: %s", operation, resource, message,
    )
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=jsonable_encoder(
            {
                "error": "service_error",
                "message": message,
                "operation": operation,
                "resource": resource,
                "context": context or {},
            }
        ),
    )


@router.post("", response_model=PRMemoryResponse)
async def create_pr_memory(
    payload: PRMemoryCreateRequest, request: Request, response: Response,
) -> PRMemoryResponse:
    try:
        payload_data = payload.model_dump()
        payload_data["project"] = resolve_project(payload_data.get("project"))
        command = CreatePRMemoryCommand(**payload_data)
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=jsonable_encoder(error.errors()),
        ) from error
    try:
        result = await _container(request).pr_memory.create_pr_memory(
            command,
        )
    except HTTPException:
        raise
    except MemoryServiceError as error:
        raise _structured_error(
            str(error),
            operation="create_pr_memory",
            resource="pr_memory",
            context=error.context,
        ) from error
    except Exception as error:
        raise _structured_error(
            str(error),
            operation="create_pr_memory",
            resource="pr_memory",
        ) from error
    if isinstance(result, dict) and result.get("status") == "pending_approval":
        response.status_code = status.HTTP_202_ACCEPTED
    return PRMemoryResponse.model_validate(result)


@router.get("", response_model=list[PRMemoryResponse])
async def query_pr_memories(
    request: Request,
    project: str | None = None,
    repo: str | None = None,
    pr_number: int | None = None,
    changed_file_contains: str | None = None,
    summary_query: str | None = None,
    limit: int = 50,
) -> list[PRMemoryResponse]:
    try:
        project = resolve_project(project)
        query_kwargs = {
            "project": project,
            "repo": repo,
            "pr_number": pr_number,
            "changed_file_contains": changed_file_contains,
        }
        if summary_query:
            query_kwargs["summary_query"] = summary_query
        if limit != 50:
            query_kwargs["limit"] = limit
        rows = await _container(request).pr_memory.query_pr_memories(
            **query_kwargs,
        )
    except HTTPException:
        raise
    except MemoryServiceError as error:
        raise _structured_error(
            str(error),
            operation="query_pr_memories",
            resource="pr_memory",
            context=error.context,
        ) from error
    except Exception as error:
        raise _structured_error(
            str(error),
            operation="query_pr_memories",
            resource="pr_memory",
        ) from error
    return [PRMemoryResponse.model_validate(item) for item in rows]
