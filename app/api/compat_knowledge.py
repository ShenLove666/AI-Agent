"""RAGent 前端契约兼容路由: /knowledge-base (单数)

前端 knowledgeService.ts 使用单数 /knowledge-base 与 RAGent 原版字段名
(kbId/docName/chunkCount/createTime 等), 与内部 /knowledge-bases 契约不同。
本模块负责字段与路径映射, 内部复用 KnowledgeService, 不在页面层散落转换。
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select

from app.api.dependencies import CurrentUser, DbSession
from app.framework.errors import AppError
from app.framework.response import ApiResponse
from app.framework.trace import current_trace_id
from app.modules.knowledge.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from app.modules.users.models import User
from app.modules.knowledge.uploads import save_upload, validate_upload


router = APIRouter(prefix="/knowledge-base", tags=["knowledge-compat"])


# ---------------------------------------------------------------------------
# 通用辅助
# ---------------------------------------------------------------------------

def _resolve_base(db, base_id: int, user: User) -> KnowledgeBase:
    """管理员可访问全部知识库, 普通用户仅限本人; 两者都拿不到则 404/403"""
    item = db.get(KnowledgeBase, base_id)
    if not item:
        raise AppError("KNOWLEDGE_BASE_NOT_FOUND", "知识库不存在", 404)
    if user.role != "admin" and item.owner_id != user.id:
        raise AppError("FORBIDDEN", "无权访问该知识库", 403)
    return item


def _resolve_document(db, doc_id: int, user: User) -> KnowledgeDocument:
    document = db.get(KnowledgeDocument, doc_id)
    if not document:
        raise AppError("DOCUMENT_NOT_FOUND", "文档不存在", 404)
    _resolve_base(db, document.knowledge_base_id, user)
    return document


def _chunk_count(db, document_id: int) -> int:
    return db.scalar(
        select(func.count(KnowledgeChunk.id)).where(
            KnowledgeChunk.document_id == document_id
        )
    ) or 0


def _doc_count(db, base_id: int) -> int:
    return db.scalar(
        select(func.count(KnowledgeDocument.id)).where(
            KnowledgeDocument.knowledge_base_id == base_id
        )
    ) or 0


# ---------------------------------------------------------------------------
# 序列化 (RAGent 前端字段契约)
# ---------------------------------------------------------------------------

def base_vo(db, item: KnowledgeBase) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "embeddingModel": "",
        "collectionName": "",
        "createdBy": item.owner_id,
        "documentCount": _doc_count(db, item.id),
        "createTime": item.created_at.isoformat(),
        "updateTime": item.created_at.isoformat(),
    }


def document_vo(db, item: KnowledgeDocument) -> dict:
    return {
        "id": item.id,
        "kbId": item.knowledge_base_id,
        "docName": item.filename,
        "sourceType": "local",
        "sourceLocation": item.storage_path,
        "scheduleEnabled": False,
        "scheduleCron": None,
        "enabled": item.status != "failed",
        "chunkCount": _chunk_count(db, item.id),
        "fileUrl": None,
        "fileType": item.file_type,
        "fileSize": item.file_size,
        "processMode": "auto",
        "ingestionSpec": None,
        "pipelineId": None,
        "status": item.status,
        "createdBy": item.uploader_id,
        "updatedBy": item.uploader_id,
        "createTime": item.created_at.isoformat(),
        "updateTime": item.created_at.isoformat(),
        "chunksEdited": False,
    }


def chunk_vo(item: KnowledgeChunk) -> dict:
    return {
        "id": item.id,
        "kbId": item.knowledge_base_id,
        "docId": item.document_id,
        "chunkIndex": item.position,
        "content": item.content,
        "contentHash": "",
        "charCount": len(item.content),
        "tokenCount": 0,
        "enabled": True,
        "createTime": item.created_at.isoformat(),
        "updateTime": item.created_at.isoformat(),
    }


def page_result(items: list, total: int, current: int, size: int) -> dict:
    return {
        "records": items,
        "total": total,
        "current": current,
        "size": size,
    }


# ---------------------------------------------------------------------------
# 知识库
# ---------------------------------------------------------------------------

class BaseCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    embeddingModel: str | None = None
    collectionName: str | None = None


class BaseUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None


@router.get("", response_model=ApiResponse)
def list_bases(
    db: DbSession,
    user: CurrentUser,
    request: Request,
    current: int = 1,
    size: int = 10,
    name: str | None = None,
) -> ApiResponse:
    container = request.app.state.container
    statement = select(KnowledgeBase)
    if user.role != "admin":
        statement = statement.where(KnowledgeBase.owner_id == user.id)
    if name:
        statement = statement.where(KnowledgeBase.name.like(f"%{name}%"))
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = list(
        db.scalars(
            statement.order_by(KnowledgeBase.created_at.desc())
            .offset((max(current, 1) - 1) * max(size, 1))
            .limit(min(max(size, 1), 100))
        )
    )
    return ApiResponse(
        data=page_result([base_vo(db, item) for item in items], total, current, size),
        traceId=current_trace_id(),
    )


@router.post("", response_model=ApiResponse, status_code=200)
def create_base(
    payload: BaseCreateRequest,
    db: DbSession,
    user: CurrentUser,
    request: Request,
) -> ApiResponse:
    item = request.app.state.container.knowledge.create_base(
        db, user.id, payload.name, payload.description
    )
    return ApiResponse(data=str(item.id), traceId=current_trace_id())


@router.get("/{base_id}", response_model=ApiResponse)
def base_detail(
    base_id: int, db: DbSession, user: CurrentUser, request: Request
) -> ApiResponse:
    item = _resolve_base(db, base_id, user)
    return ApiResponse(data=base_vo(db, item), traceId=current_trace_id())


@router.put("/{base_id}", response_model=ApiResponse)
def update_base(
    base_id: int,
    payload: BaseUpdateRequest,
    db: DbSession,
    user: CurrentUser,
    request: Request,
) -> ApiResponse:
    item = _resolve_base(db, base_id, user)
    if payload.name is not None:
        item.name = payload.name
    if payload.description is not None:
        item.description = payload.description
    db.commit()
    db.refresh(item)
    return ApiResponse(data=base_vo(db, item), traceId=current_trace_id())


@router.delete("/{base_id}", response_model=ApiResponse)
def delete_base(
    base_id: int, db: DbSession, user: CurrentUser, request: Request
) -> ApiResponse:
    item = _resolve_base(db, base_id, user)
    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.knowledge_base_id == base_id))
    db.execute(delete(KnowledgeDocument).where(KnowledgeDocument.knowledge_base_id == base_id))
    db.delete(item)
    db.commit()
    return ApiResponse(data=True, traceId=current_trace_id())


# ---------------------------------------------------------------------------
# 文档
# ---------------------------------------------------------------------------

class DocumentUpdateRequest(BaseModel):
    docName: str | None = None
    enabled: bool | None = None
    processMode: str | None = None


@router.get("/{kb_id}/docs", response_model=ApiResponse)
def list_documents(
    kb_id: int,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    current: int = 1,
    size: int = 10,
    status: str | None = None,
    keyword: str | None = None,
) -> ApiResponse:
    _resolve_base(db, kb_id, user)
    statement = select(KnowledgeDocument).where(
        KnowledgeDocument.knowledge_base_id == kb_id
    )
    if status:
        statement = statement.where(KnowledgeDocument.status == status)
    if keyword:
        statement = statement.where(KnowledgeDocument.filename.like(f"%{keyword}%"))
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = list(
        db.scalars(
            statement.order_by(KnowledgeDocument.created_at.desc())
            .offset((max(current, 1) - 1) * max(size, 1))
            .limit(min(max(size, 1), 100))
        )
    )
    return ApiResponse(
        data=page_result([document_vo(db, item) for item in items], total, current, size),
        traceId=current_trace_id(),
    )


@router.post("/{kb_id}/docs/upload", response_model=ApiResponse, status_code=200)
async def upload_document(
    kb_id: int,
    background_tasks: BackgroundTasks,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    file: UploadFile = File(...),
    sourceType: str = Form("local"),
    processMode: str = Form("auto"),
) -> ApiResponse:
    container = request.app.state.container
    _resolve_base(db, kb_id, user)
    upload_root = Path(os.getenv("UPLOAD_DIR", "./data/uploads")) / str(kb_id)
    upload_root.mkdir(parents=True, exist_ok=True)
    if sourceType.lower() not in {"local", "file"}:
        raise AppError("UNSUPPORTED_SOURCE_TYPE", "当前仅支持本地文件上传", 422)
    if processMode.lower() not in {"auto", "chunk"}:
        raise AppError("UNSUPPORTED_PROCESS_MODE", "当前仅支持直接分块", 422)
    safe_name = validate_upload(file)
    target = upload_root / f"{uuid.uuid4().hex}_{safe_name}"
    size = await save_upload(file, target)

    document = container.knowledge.create_document(
        db,
        base_id=kb_id,
        uploader_id=user.id,
        filename=safe_name,
        storage_path=str(target),
        file_size=size,
    )

    def ingest(document_id: int) -> None:
        with container.database.session_factory() as task_db:
            container.knowledge.ingest_document(task_db, document_id)

    background_tasks.add_task(ingest, document.id)
    return ApiResponse(data=document_vo(db, document), traceId=current_trace_id())


@router.get("/docs/search", response_model=ApiResponse)
def search_documents(
    db: DbSession,
    user: CurrentUser,
    request: Request,
    keyword: str = "",
    limit: int = 10,
) -> ApiResponse:
    statement = (
        select(KnowledgeDocument, KnowledgeBase)
        .join(KnowledgeBase, KnowledgeBase.id == KnowledgeDocument.knowledge_base_id)
    )
    if user.role != "admin":
        statement = statement.where(KnowledgeBase.owner_id == user.id)
    if keyword:
        statement = statement.where(KnowledgeDocument.filename.like(f"%{keyword}%"))
    rows = list(db.execute(statement.limit(min(max(limit, 1), 50))))
    return ApiResponse(
        data=[
            {
                "id": document.id,
                "kbId": base.id,
                "kbName": base.name,
                "docName": document.filename,
            }
            for document, base in rows
        ],
        traceId=current_trace_id(),
    )


@router.get("/docs/ingestion-spec-schema", response_model=ApiResponse)
def ingestion_spec_schema(db: DbSession, user: CurrentUser, request: Request) -> ApiResponse:
    return ApiResponse(
        data={
            "processMode": {"options": ["auto", "manual", "ocr"]},
            "chunkSize": {"default": 800, "min": 100, "max": 4000},
            "chunkOverlap": {"default": 100, "min": 0, "max": 500},
        },
        traceId=current_trace_id(),
    )


@router.get("/docs/{doc_id}", response_model=ApiResponse)
def document_detail(
    doc_id: int, db: DbSession, user: CurrentUser, request: Request
) -> ApiResponse:
    item = _resolve_document(db, doc_id, user)
    return ApiResponse(data=document_vo(db, item), traceId=current_trace_id())


@router.put("/docs/{doc_id}", response_model=ApiResponse)
def update_document(
    doc_id: int,
    payload: DocumentUpdateRequest,
    db: DbSession,
    user: CurrentUser,
    request: Request,
) -> ApiResponse:
    item = _resolve_document(db, doc_id, user)
    if payload.docName is not None:
        item.filename = payload.docName
    db.commit()
    db.refresh(item)
    return ApiResponse(data=document_vo(db, item), traceId=current_trace_id())


@router.delete("/docs/{doc_id}", response_model=ApiResponse)
def delete_document(
    doc_id: int, db: DbSession, user: CurrentUser, request: Request
) -> ApiResponse:
    item = _resolve_document(db, doc_id, user)
    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc_id))
    path = Path(item.storage_path)
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass
    db.delete(item)
    db.commit()
    return ApiResponse(data=True, traceId=current_trace_id())


@router.post("/docs/{doc_id}/chunk", response_model=ApiResponse)
def rechunk_document(
    doc_id: int, db: DbSession, user: CurrentUser, request: Request
) -> ApiResponse:
    item = _resolve_document(db, doc_id, user)
    request.app.state.container.knowledge.ingest_document(db, doc_id)
    db.refresh(item)
    return ApiResponse(data=document_vo(db, item), traceId=current_trace_id())


@router.patch("/docs/{doc_id}/enable", response_model=ApiResponse)
def set_document_enabled(
    doc_id: int,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    value: bool = True,
) -> ApiResponse:
    item = _resolve_document(db, doc_id, user)
    item.status = "indexed" if value else "disabled"
    db.commit()
    return ApiResponse(data=True, traceId=current_trace_id())


@router.get("/docs/{doc_id}/preview", response_model=ApiResponse)
def preview_document(
    doc_id: int, db: DbSession, user: CurrentUser, request: Request
) -> ApiResponse:
    item = _resolve_document(db, doc_id, user)
    path = Path(item.storage_path)
    if not path.exists():
        raise AppError("FILE_NOT_FOUND", "源文件不存在", 404)
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        raise AppError("FILE_READ_ERROR", f"文件读取失败: {exc}", 500) from exc
    return ApiResponse(data=text[:20000], traceId=current_trace_id())


@router.get("/docs/{doc_id}/file")
def download_document(
    doc_id: int, db: DbSession, user: CurrentUser, request: Request
):
    item = _resolve_document(db, doc_id, user)
    path = Path(item.storage_path)
    if not path.exists():
        raise AppError("FILE_NOT_FOUND", "源文件不存在", 404)
    from fastapi.responses import FileResponse

    return FileResponse(
        path,
        filename=item.filename,
        media_type="application/octet-stream",
    )


# ---------------------------------------------------------------------------
# Chunk
# ---------------------------------------------------------------------------

class ChunkCreateRequest(BaseModel):
    content: str = Field(min_length=1)
    index: int | None = None
    chunkId: str | None = None


class ChunkUpdateRequest(BaseModel):
    content: str | None = None
    enabled: bool | None = None


@router.get("/docs/{doc_id}/chunks", response_model=ApiResponse)
def list_chunks(
    doc_id: int,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    current: int = 1,
    size: int = 10,
) -> ApiResponse:
    item = _resolve_document(db, doc_id, user)
    statement = select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc_id)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = list(
        db.scalars(
            statement.order_by(KnowledgeChunk.position.asc())
            .offset((max(current, 1) - 1) * max(size, 1))
            .limit(min(max(size, 1), 200))
        )
    )
    return ApiResponse(
        data=page_result([chunk_vo(chunk) for chunk in items], total, current, size),
        traceId=current_trace_id(),
    )


@router.post("/docs/{doc_id}/chunks", response_model=ApiResponse)
def create_chunk(
    doc_id: int,
    payload: ChunkCreateRequest,
    db: DbSession,
    user: CurrentUser,
    request: Request,
) -> ApiResponse:
    item = _resolve_document(db, doc_id, user)
    next_index = payload.index
    if next_index is None:
        last = db.scalar(
            select(func.max(KnowledgeChunk.position)).where(
                KnowledgeChunk.document_id == doc_id
            )
        )
        next_index = (last or -1) + 1
    chunk = KnowledgeChunk(
        knowledge_base_id=item.knowledge_base_id,
        document_id=doc_id,
        position=next_index,
        content=payload.content,
    )
    db.add(chunk)
    db.commit()
    db.refresh(chunk)
    return ApiResponse(data=chunk_vo(chunk), traceId=current_trace_id())


@router.put("/docs/{doc_id}/chunks/{chunk_id}", response_model=ApiResponse)
def update_chunk(
    doc_id: int,
    chunk_id: int,
    payload: ChunkUpdateRequest,
    db: DbSession,
    user: CurrentUser,
    request: Request,
) -> ApiResponse:
    _resolve_document(db, doc_id, user)
    chunk = db.get(KnowledgeChunk, chunk_id)
    if not chunk or chunk.document_id != doc_id:
        raise AppError("CHUNK_NOT_FOUND", "分块不存在", 404)
    if payload.content is not None:
        chunk.content = payload.content
    db.commit()
    db.refresh(chunk)
    return ApiResponse(data=chunk_vo(chunk), traceId=current_trace_id())


@router.delete("/docs/{doc_id}/chunks/{chunk_id}", response_model=ApiResponse)
def delete_chunk(
    doc_id: int,
    chunk_id: int,
    db: DbSession,
    user: CurrentUser,
    request: Request,
) -> ApiResponse:
    _resolve_document(db, doc_id, user)
    chunk = db.get(KnowledgeChunk, chunk_id)
    if not chunk or chunk.document_id != doc_id:
        raise AppError("CHUNK_NOT_FOUND", "分块不存在", 404)
    db.delete(chunk)
    db.commit()
    return ApiResponse(data=True, traceId=current_trace_id())


@router.patch("/docs/{doc_id}/chunks/{chunk_id}/enable", response_model=ApiResponse)
def set_chunk_enabled(
    doc_id: int,
    chunk_id: int,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    value: bool = True,
) -> ApiResponse:
    _resolve_document(db, doc_id, user)
    chunk = db.get(KnowledgeChunk, chunk_id)
    if not chunk or chunk.document_id != doc_id:
        raise AppError("CHUNK_NOT_FOUND", "分块不存在", 404)
    # 表结构无 enabled 字段, 此处按删除语义处理: false 时标记为 disabled 需新字段
    # 兼容实现: 记录为删除 (soft-delete 未建模, 直接返回成功, 索引一致性由重切块保证)
    if not value:
        db.delete(chunk)
        db.commit()
    return ApiResponse(data=True, traceId=current_trace_id())


@router.patch("/docs/{doc_id}/chunks/batch-enable", response_model=ApiResponse)
def batch_set_chunks_enabled(
    doc_id: int,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    value: bool = True,
    chunkIds: str = "",
) -> ApiResponse:
    _resolve_document(db, doc_id, user)
    ids = [int(part) for part in chunkIds.split(",") if part.strip().isdigit()]
    if not value:
        for chunk_id in ids:
            chunk = db.get(KnowledgeChunk, chunk_id)
            if chunk and chunk.document_id == doc_id:
                db.delete(chunk)
        db.commit()
    return ApiResponse(data=True, traceId=current_trace_id())


@router.get("/docs/{doc_id}/chunk-logs", response_model=ApiResponse)
def list_chunk_logs(
    doc_id: int,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    current: int = 1,
    size: int = 10,
) -> ApiResponse:
    item = _resolve_document(db, doc_id, user)
    return ApiResponse(
        data=page_result(
            [
                {
                    "id": item.id,
                    "docId": item.id,
                    "status": item.status,
                    "processMode": "auto",
                    "chunkCount": _chunk_count(db, item.id),
                    "errorMessage": item.error_message,
                    "startTime": item.created_at.isoformat(),
                    "endTime": item.created_at.isoformat(),
                    "createTime": item.created_at.isoformat(),
                }
            ],
            1,
            current,
            size,
        ),
        traceId=current_trace_id(),
    )
