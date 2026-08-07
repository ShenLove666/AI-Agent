from __future__ import annotations

import asyncio
import re

import jieba
from sqlalchemy import or_, select

from app.framework.database import Database
from app.modules.knowledge.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from app.modules.retrieval.channels import BaseSearchChannel
from app.modules.retrieval.models import RetrievalRequest, SearchResult


STOP_WORDS = {"什么", "怎么", "如何", "是否", "一个", "这个", "那个", "请问", "介绍"}


def tokenize_query(query: str) -> list[str]:
    chinese_terms = [
        token.strip()
        for token in jieba.cut(query, cut_all=False)
        if len(token.strip()) >= 2 and token.strip() not in STOP_WORDS
    ]
    latin_terms = re.findall(r"[A-Za-z0-9][A-Za-z0-9_.-]+", query)
    return list(dict.fromkeys(chinese_terms + latin_terms))


class SqlKeywordSearchChannel(BaseSearchChannel):
    name = "keyword"

    def __init__(self, database: Database, *, weight: float = 1.0, enabled: bool = True):
        super().__init__(weight=weight, enabled=enabled)
        self.database = database

    async def search(self, request: RetrievalRequest) -> list[SearchResult]:
        return await asyncio.to_thread(self._search_sync, request)

    def _search_sync(self, request: RetrievalRequest) -> list[SearchResult]:
        terms = tokenize_query(request.query)
        if not terms:
            return []
        with self.database.session_factory() as db:
            statement = (
                select(KnowledgeChunk, KnowledgeDocument)
                .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
                .join(KnowledgeBase, KnowledgeBase.id == KnowledgeChunk.knowledge_base_id)
                .where(or_(*(KnowledgeChunk.content.contains(term) for term in terms)))
                .limit(request.candidate_limit * 3)
            )
            if user_id := request.metadata.get("user_id"):
                statement = statement.where(KnowledgeBase.owner_id == int(user_id))
            if request.knowledge_base_ids:
                statement = statement.where(
                    KnowledgeChunk.knowledge_base_id.in_(
                        [int(item) for item in request.knowledge_base_ids]
                    )
                )
            rows = db.execute(statement).all()

        results: list[SearchResult] = []
        for chunk, document in rows:
            matched_terms = [term for term in terms if term.lower() in chunk.content.lower()]
            results.append(
                SearchResult(
                    id=str(chunk.id),
                    content=chunk.content,
                    score=len(matched_terms) / len(terms),
                    channel=self.name,
                    source=document.filename,
                    metadata={
                        "chunk_id": chunk.id,
                        "document_id": document.id,
                        "knowledge_base_id": chunk.knowledge_base_id,
                        "position": chunk.position,
                        "matched_terms": matched_terms,
                    },
                )
            )
        return sorted(results, key=lambda item: item.score, reverse=True)[: request.candidate_limit]
