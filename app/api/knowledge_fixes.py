from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import delete, func, select

from app.api.dependencies import (
    CurrentUser,
    DbSession,
    make_permission_requirement,
)
from app.framework.errors import AppError
from app.framework.response import ApiResponse
from app.framework.trace import current_trace_id
from app.modules.knowledge.models import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
)

router = APIRouter(prefix="/knowledge-base", tags=["knowledge-compat"])


def _base(db, base_id: int, user) -> KnowledgeBase:
    item = db.get(KnowledgeBase, base_id)
    if item is None:
        raise AppError("KNOWLEDGE_BASE_NOT_FOUND", "知识库不存在", 404)
    if user.role != "admin" and item.owner_id != user.id:
        raise AppError("FORBIDDEN", "无权访问该知识库", 403)
    return item


def _document(db, document_id: int, user) -> KnowledgeDocument:
    item = db.get(KnowledgeDocument, document_id)
    if item is None:
        raise AppError("DOCUMENT_NOT_FOUND", "文档不存在", 404)
    _base(db, item.knowledge_base_id, user)
    return item


def _chunk(db, document_id: int, chunk_id: int, user) -> KnowledgeChunk:
    _document(db, document_id, user)
    item = db.get(KnowledgeChunk, chunk_id)
    if item is None or item.document_id != document_id:
        raise AppError("CHUNK_NOT_FOUND", "分块不存在", 404)
    return item


def _page(records: list, total: int, current: int, size: int) -> dict:
    normalized_size = max(size, 1)
    return {
        "records": records,
        "total": total,
        "size": normalized_size,
        "current": max(current, 1),
        "pages": (total + normalized_size - 1) // normalized_size,
    }


def _base_vo(db, item: KnowledgeBase) -> dict:
    count = (
        db.scalar(
            select(func.count(KnowledgeDocument.id)).where(
                KnowledgeDocument.knowledge_base_id == item.id
            )
        )
        or 0
    )
    return {
        "id": str(item.id),
        "name": item.name,
        "embeddingModel": os.getenv("EMBED_MODEL_PATH") or "bge-small-zh-v1.5",
        "collectionName": os.getenv("MILVUS_COLLECTION", "ragent_chunks_v2"),
        "createdBy": str(item.owner_id),
        "documentCount": count,
        "createTime": item.created_at.isoformat(),
        "updateTime": item.created_at.isoformat(),
    }


def _document_vo(db, item: KnowledgeDocument) -> dict:
    count = (
        db.scalar(
            select(func.count(KnowledgeChunk.id)).where(
                KnowledgeChunk.document_id == item.id
            )
        )
        or 0
    )
    return {
        "id": str(item.id),
        "kbId": str(item.knowledge_base_id),
        "docName": item.filename,
        "sourceType": "file",
        "sourceLocation": None,
        "enabled": item.enabled,
        "chunkCount": count,
        "fileType": item.file_type,
        "fileSize": item.file_size,
        "processMode": "chunk",
        "status": item.status,
        "createdBy": str(item.uploader_id),
        "updatedBy": str(item.uploader_id),
        "createTime": item.created_at.isoformat(),
        "updateTime": item.created_at.isoformat(),
        "chunksEdited": False,
    }


def _chunk_vo(item: KnowledgeChunk) -> dict:
    return {
        "id": str(item.id),
        "kbId": str(item.knowledge_base_id),
        "docId": str(item.document_id),
        "chunkIndex": item.position,
        "content": item.content,
        "contentHash": "",
        "charCount": len(item.content),
        "tokenCount": None,
        "enabled": 1 if item.enabled else 0,
        "createTime": item.created_at.isoformat(),
        "updateTime": item.created_at.isoformat(),
    }


async def _reindex(db, request: Request, document: KnowledgeDocument) -> None:
    indexer = request.app.state.container.knowledge.vector_indexer
    if indexer is None:
        return
    await indexer.store.delete_document(document.id)
    if not document.enabled:
        return
    chunks = list(
        db.scalars(
            select(KnowledgeChunk)
            .where(
                KnowledgeChunk.document_id == document.id,
                KnowledgeChunk.enabled.is_(True),
            )
            .order_by(KnowledgeChunk.position.asc())
        )
    )
    if chunks:
        await indexer.index(
            owner_id=document.uploader_id,
            knowledge_base_id=document.knowledge_base_id,
            document_id=document.id,
            source=document.filename,
            chunks=[(item.id, item.position, item.content) for item in chunks],
        )


@router.get("", dependencies=[Depends(make_permission_requirement("knowledge.manage"))])
def list_bases(
    db: DbSession,
    user: CurrentUser,
    current: int = 1,
    size: int = 10,
    name: str | None = None,
) -> ApiResponse:
    statement = select(KnowledgeBase)
    if user.role != "admin":
        statement = statement.where(KnowledgeBase.owner_id == user.id)
    if name:
        statement = statement.where(KnowledgeBase.name.contains(name))
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = list(
        db.scalars(
            statement.order_by(KnowledgeBase.created_at.desc())
            .offset((max(current, 1) - 1) * max(size, 1))
            .limit(min(max(size, 1), 200))
        )
    )
    return ApiResponse(
        data=_page([_base_vo(db, row) for row in rows], total, current, size),
        traceId=current_trace_id(),
    )


@router.get("/{base_id}/docs", dependencies=[Depends(make_permission_requirement("knowledge.manage"))])
def list_documents(
    base_id: int,
    db: DbSession,
    user: CurrentUser,
    current: int = 1,
    size: int = 10,
    status: str | None = None,
    keyword: str | None = None,
) -> ApiResponse:
    _base(db, base_id, user)
    statement = select(KnowledgeDocument).where(
        KnowledgeDocument.knowledge_base_id == base_id
    )
    if status:
        statement = statement.where(KnowledgeDocument.status == status)
    if keyword:
        statement = statement.where(KnowledgeDocument.filename.contains(keyword))
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = list(
        db.scalars(
            statement.order_by(KnowledgeDocument.created_at.desc())
            .offset((max(current, 1) - 1) * max(size, 1))
            .limit(min(max(size, 1), 200))
        )
    )
    return ApiResponse(
        data=_page([_document_vo(db, row) for row in rows], total, current, size),
        traceId=current_trace_id(),
    )


@router.get("/docs/ingestion-spec-schema", dependencies=[Depends(make_permission_requirement("knowledge.manage"))])
def ingestion_schema(user: CurrentUser) -> ApiResponse:
    return ApiResponse(
        data={
            "parseProfileLabel": "解析方式",
            "parseProfiles": [
                {
                    "value": "balanced",
                    "label": "通用解析",
                    "hint": "适合普通文本、PDF 与 Word",
                },
                {"value": "table", "label": "表格优先", "hint": "适合 CSV 与电子表格"},
            ],
            "parseProfileExtensions": ["csv", "xls", "xlsx"],
            "budgetFields": [
                {
                    "key": "maxChars",
                    "label": "每块最大字符数",
                    "defaultValue": 800,
                    "min": 100,
                    "max": 4000,
                    "recommendedMin": 500,
                    "recommendedMax": 1200,
                    "hint": "控制检索粒度",
                },
                {
                    "key": "overlapChars",
                    "label": "重叠字符数",
                    "defaultValue": 100,
                    "min": 0,
                    "max": 500,
                    "recommendedMin": 50,
                    "recommendedMax": 200,
                    "hint": "保留分块边界上下文",
                },
            ],
            "wholeDocumentSentinel": -1,
        },
        traceId=current_trace_id(),
    )


@router.get("/docs/{document_id}/chunks", dependencies=[Depends(make_permission_requirement("knowledge.manage"))])
def list_chunks(
    document_id: int,
    db: DbSession,
    user: CurrentUser,
    current: int = 1,
    size: int = 10,
    enabled: int | None = None,
) -> ApiResponse:
    _document(db, document_id, user)
    statement = select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)
    if enabled is not None:
        statement = statement.where(KnowledgeChunk.enabled.is_(bool(enabled)))
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = list(
        db.scalars(
            statement.order_by(KnowledgeChunk.position.asc())
            .offset((max(current, 1) - 1) * max(size, 1))
            .limit(min(max(size, 1), 200))
        )
    )
    return ApiResponse(
        data=_page([_chunk_vo(row) for row in rows], total, current, size),
        traceId=current_trace_id(),
    )


class ChunkIdsRequest(BaseModel):
    chunkIds: list[int | str]


@router.patch("/docs/{document_id}/enable", dependencies=[Depends(make_permission_requirement("knowledge.manage"))])
async def set_document_enabled(
    document_id: int,
    request: Request,
    db: DbSession,
    user: CurrentUser,
    value: bool = True,
) -> ApiResponse:
    document = _document(db, document_id, user)
    document.enabled = value
    db.commit()
    await _reindex(db, request, document)
    return ApiResponse(data=True, traceId=current_trace_id())


@router.patch("/docs/{document_id}/chunks/{chunk_id}/enable", dependencies=[Depends(make_permission_requirement("knowledge.manage"))])
async def set_chunk_enabled(
    document_id: int,
    chunk_id: int,
    request: Request,
    db: DbSession,
    user: CurrentUser,
    value: bool = True,
) -> ApiResponse:
    item = _chunk(db, document_id, chunk_id, user)
    item.enabled = value
    db.commit()
    await _reindex(db, request, _document(db, document_id, user))
    return ApiResponse(data=True, traceId=current_trace_id())


@router.patch("/docs/{document_id}/chunks/batch-enable", dependencies=[Depends(make_permission_requirement("knowledge.manage"))])
async def batch_set_chunks_enabled(
    document_id: int,
    payload: ChunkIdsRequest,
    request: Request,
    db: DbSession,
    user: CurrentUser,
    value: bool = True,
) -> ApiResponse:
    document = _document(db, document_id, user)
    ids: set[int] = set()
    for item in payload.chunkIds:
        try:
            ids.add(int(item))
        except (TypeError, ValueError):
            continue
    chunks = list(
        db.scalars(
            select(KnowledgeChunk).where(
                KnowledgeChunk.document_id == document_id,
                KnowledgeChunk.id.in_(ids),
            )
        )
    )
    for item in chunks:
        item.enabled = value
    db.commit()
    await _reindex(db, request, document)
    return ApiResponse(data={"updated": len(chunks)}, traceId=current_trace_id())


@router.delete("/docs/{document_id}", dependencies=[Depends(make_permission_requirement("knowledge.manage"))])
async def delete_document(
    document_id: int,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse:
    document = _document(db, document_id, user)
    indexer = request.app.state.container.knowledge.vector_indexer
    if indexer is not None:
        await indexer.store.delete_document(document.id)
    path = Path(document.storage_path)
    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id))
    db.delete(document)
    db.commit()
    path.unlink(missing_ok=True)
    return ApiResponse(data=True, traceId=current_trace_id())


@router.delete("/{base_id}", dependencies=[Depends(make_permission_requirement("knowledge.manage"))])
async def delete_base(
    base_id: int,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse:
    base = _base(db, base_id, user)
    documents = list(
        db.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.knowledge_base_id == base_id
            )
        )
    )
    indexer = request.app.state.container.knowledge.vector_indexer
    if indexer is not None:
        for document in documents:
            await indexer.store.delete_document(document.id)
    paths = [Path(document.storage_path) for document in documents]
    db.execute(
        delete(KnowledgeChunk).where(KnowledgeChunk.knowledge_base_id == base_id)
    )
    db.execute(
        delete(KnowledgeDocument).where(KnowledgeDocument.knowledge_base_id == base_id)
    )
    db.delete(base)
    db.commit()
    for path in paths:
        path.unlink(missing_ok=True)
    return ApiResponse(data=True, traceId=current_trace_id())
