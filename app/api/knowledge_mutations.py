from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import delete

from app.api.dependencies import (
    CurrentUser,
    DbSession,
    make_permission_requirement,
)
from app.framework.errors import AppError
from app.modules.knowledge.models import KnowledgeChunk, KnowledgeDocument
from app.modules.users.access import resolve_owner


router = APIRouter(prefix="/knowledge-bases", tags=["knowledge"])


@router.delete(
    "/{base_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT
, dependencies=[Depends(make_permission_requirement("knowledge.manage"))])
async def delete_document(
    base_id: int,
    document_id: int,
    db: DbSession,
    user: CurrentUser,
    request: Request,
) -> Response:
    container = request.app.state.container
    # 归属校验用商家数据 owner（组织成员 → 组织 owner_user_id），
    # actor（登录 user）与 owner 分离，与 knowledge.py 的 require_owned_base
    # 语义一致：跨商家 base 一律 404 KNOWLEDGE_BASE_NOT_FOUND。
    data_owner_id = resolve_owner(db, user)
    container.knowledge.require_owned_base(db, base_id, data_owner_id)
    document = db.get(KnowledgeDocument, document_id)
    if not document or document.knowledge_base_id != base_id:
        raise AppError("DOCUMENT_NOT_FOUND", "文档不存在", 404)

    indexer = container.knowledge.vector_indexer
    if indexer is not None:
        await indexer.store.delete_document(document_id)
    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id))
    db.delete(document)
    db.commit()
    path = Path(document.storage_path)
    if path.is_file():
        path.unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
