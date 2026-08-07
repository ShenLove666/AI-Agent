from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Request, UploadFile
from pydantic import BaseModel, Field

from app.api.dependencies import CurrentUserId, DbSession
from app.framework.response import ApiResponse
from app.framework.trace import current_trace_id
from app.modules.knowledge.uploads import save_upload, validate_upload


router = APIRouter(prefix="/knowledge-bases", tags=["knowledge"])


class KnowledgeBaseCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None


def serialize_base(item):
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "createdAt": item.created_at.isoformat(),
    }


def serialize_document(item):
    return {
        "id": item.id,
        "knowledgeBaseId": item.knowledge_base_id,
        "filename": item.filename,
        "fileType": item.file_type,
        "fileSize": item.file_size,
        "status": item.status,
        "error": item.error_message,
        "createdAt": item.created_at.isoformat(),
    }


@router.post("", response_model=ApiResponse, status_code=201)
def create_base(
    payload: KnowledgeBaseCreateRequest,
    db: DbSession,
    user_id: CurrentUserId,
    request: Request,
) -> ApiResponse:
    item = request.app.state.container.knowledge.create_base(
        db, user_id, payload.name, payload.description
    )
    return ApiResponse(data=serialize_base(item), traceId=current_trace_id())


@router.get("", response_model=ApiResponse)
def list_bases(db: DbSession, user_id: CurrentUserId, request: Request) -> ApiResponse:
    items = request.app.state.container.knowledge.list_bases(db, user_id)
    return ApiResponse(data=[serialize_base(item) for item in items], traceId=current_trace_id())


@router.get("/{base_id}/documents", response_model=ApiResponse)
def list_documents(
    base_id: int, db: DbSession, user_id: CurrentUserId, request: Request
) -> ApiResponse:
    items = request.app.state.container.knowledge.list_documents(db, base_id, user_id)
    return ApiResponse(
        data=[serialize_document(item) for item in items], traceId=current_trace_id()
    )


@router.post("/{base_id}/documents", response_model=ApiResponse, status_code=202)
async def upload_document(
    base_id: int,
    background_tasks: BackgroundTasks,
    db: DbSession,
    user_id: CurrentUserId,
    request: Request,
    file: UploadFile = File(...),
) -> ApiResponse:
    container = request.app.state.container
    container.knowledge.require_owned_base(db, base_id, user_id)
    upload_root = Path(os.getenv("UPLOAD_DIR", "./data/uploads")) / str(base_id)
    upload_root.mkdir(parents=True, exist_ok=True)
    safe_name = validate_upload(file)
    target = upload_root / f"{uuid.uuid4().hex}_{safe_name}"
    size = await save_upload(file, target)

    document = container.knowledge.create_document(
        db,
        base_id=base_id,
        uploader_id=user_id,
        filename=safe_name,
        storage_path=str(target),
        file_size=size,
    )

    def ingest(document_id: int) -> None:
        with container.database.session_factory() as task_db:
            container.knowledge.ingest_document(task_db, document_id)

    background_tasks.add_task(ingest, document.id)
    return ApiResponse(data=serialize_document(document), traceId=current_trace_id())
