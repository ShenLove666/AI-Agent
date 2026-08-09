from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.dependencies import (
    CurrentUser,
    DbSession,
    make_permission_requirement,
)
from app.api.knowledge_fixes import _chunk, _chunk_vo, _document, _reindex
from app.framework.errors import AppError
from app.framework.response import ApiResponse
from app.framework.trace import current_trace_id
from app.modules.knowledge.models import KnowledgeChunk


router = APIRouter(prefix="/knowledge-base", tags=["knowledge-compat"])


class ChunkCreateRequest(BaseModel):
    content: str = Field(min_length=1)
    index: int | None = None
    chunkId: str | None = None


class ChunkUpdateRequest(BaseModel):
    content: str = Field(min_length=1)


@router.post("/docs/{document_id}/chunks", dependencies=[Depends(make_permission_requirement("knowledge.manage"))])
async def create_chunk(
    document_id: int,
    payload: ChunkCreateRequest,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse:
    document = _document(db, document_id, user)
    content = payload.content.strip()
    if not content:
        raise AppError("INVALID_CHUNK", "分块内容不能为空", 422)
    position = payload.index
    if position is None:
        last_position = db.scalar(
            select(func.max(KnowledgeChunk.position)).where(
                KnowledgeChunk.document_id == document_id
            )
        )
        position = (last_position if last_position is not None else -1) + 1
    item = KnowledgeChunk(
        knowledge_base_id=document.knowledge_base_id,
        document_id=document.id,
        position=position,
        content=content,
        enabled=True,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    await _reindex(db, request, document)
    return ApiResponse(data=_chunk_vo(item), traceId=current_trace_id())


@router.put("/docs/{document_id}/chunks/{chunk_id}", dependencies=[Depends(make_permission_requirement("knowledge.manage"))])
async def update_chunk(
    document_id: int,
    chunk_id: int,
    payload: ChunkUpdateRequest,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse:
    document = _document(db, document_id, user)
    item = _chunk(db, document_id, chunk_id, user)
    content = payload.content.strip()
    if not content:
        raise AppError("INVALID_CHUNK", "分块内容不能为空", 422)
    item.content = content
    db.commit()
    db.refresh(item)
    await _reindex(db, request, document)
    return ApiResponse(data=_chunk_vo(item), traceId=current_trace_id())


@router.delete("/docs/{document_id}/chunks/{chunk_id}", dependencies=[Depends(make_permission_requirement("knowledge.manage"))])
async def delete_chunk(
    document_id: int,
    chunk_id: int,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse:
    document = _document(db, document_id, user)
    item = _chunk(db, document_id, chunk_id, user)
    db.delete(item)
    db.commit()
    await _reindex(db, request, document)
    return ApiResponse(data=True, traceId=current_trace_id())
