from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import delete

from app.api.dependencies import CurrentUserId, DbSession
from app.framework.errors import AppError
from app.modules.knowledge.models import KnowledgeChunk, KnowledgeDocument


router = APIRouter(prefix="/knowledge-bases", tags=["knowledge"])


@router.delete(
    "/{base_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_document(
    base_id: int,
    document_id: int,
    db: DbSession,
    user_id: CurrentUserId,
    request: Request,
) -> Response:
    container = request.app.state.container
    container.knowledge.require_owned_base(db, base_id, user_id)
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
