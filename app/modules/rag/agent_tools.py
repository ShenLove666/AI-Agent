from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.framework.errors import AppError
from app.modules.commerce.models import AssociationRule, Basket, BasketItem, CommerceImport, Product
from app.modules.knowledge.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from app.modules.orders.service import OrderService
from app.modules.retrieval.engine import MultiChannelRetrievalEngine
from app.modules.retrieval.models import RetrievalRequest, SearchResult
from app.modules.support.models import KnowledgeGap, SupportCase, SupportQualityLabel


class _ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QueryInput(_ToolInput):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=6, ge=1, le=20)


class RecordInput(_ToolInput):
    record_id: int = Field(gt=0)


class ProductMetricsInput(_ToolInput):
    query: str | None = Field(default=None, max_length=100)
    limit: int = Field(default=8, ge=1, le=20)


class AssociationInput(_ToolInput):
    query: str | None = Field(default=None, max_length=100)
    min_lift: float = Field(default=1.0, ge=0, le=100)
    limit: int = Field(default=8, ge=1, le=20)


class SupportSearchInput(_ToolInput):
    query: str | None = Field(default=None, max_length=200)
    status: str | None = Field(default=None, max_length=30)
    limit: int = Field(default=8, ge=1, le=20)


class OrderLookupInput(_ToolInput):
    order_no: str = Field(min_length=1, max_length=80)


class ToolEvidence(BaseModel):
    id: str
    content: str
    source: str
    score: float = 1.0
    provenance: str = "derived"
    metadata: dict[str, Any] = Field(default_factory=dict)

    def as_search_result(self, channel: str) -> SearchResult:
        return SearchResult(self.id, self.content, self.score, channel, self.source, {
            **self.metadata, "provenance": self.provenance, "tool": channel,
        })


class ToolResult(BaseModel):
    tool: str
    status: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    evidence: list[ToolEvidence] = Field(default_factory=list)
    duration_ms: int = 0
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class ToolContext:
    db: Session
    owner_id: int
    knowledge_base_ids: tuple[int, ...] = ()


ToolHandler = Callable[[ToolContext, BaseModel], Awaitable[list[ToolEvidence]]]


@dataclass(frozen=True, slots=True)
class AgentTool:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: ToolHandler


class ToolRegistry:
    def __init__(self, tools: list[AgentTool], aliases: dict[str, str] | None = None):
        self._tools = {tool.name: tool for tool in tools}
        self._aliases = dict(aliases or {})

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted((*self._tools, *self._aliases)))

    def canonical_name(self, name: str) -> str | None:
        candidate = self._aliases.get(name, name)
        return candidate if candidate in self._tools else None

    def describe(self) -> list[dict[str, Any]]:
        return [{"name": item.name, "description": item.description, "inputSchema": item.input_model.model_json_schema()} for item in self._tools.values()]

    async def execute(self, name: str, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        started = time.perf_counter()
        canonical = self.canonical_name(name)
        if canonical is None:
            return ToolResult(tool=name, status="error", arguments={}, duration_ms=self._elapsed(started), error_code="TOOL_NOT_FOUND", error_message="未注册的工具")
        tool = self._tools[canonical]
        try:
            parsed = tool.input_model.model_validate(arguments)
        except ValidationError:
            return ToolResult(tool=canonical, status="error", arguments={}, duration_ms=self._elapsed(started), error_code="TOOL_INPUT_INVALID", error_message="工具参数校验失败")
        safe_arguments = parsed.model_dump(exclude_none=True)
        try:
            evidence = await tool.handler(context, parsed)
            return ToolResult(tool=canonical, status="success", arguments=safe_arguments, evidence=evidence, duration_ms=self._elapsed(started))
        except Exception:
            return ToolResult(tool=canonical, status="error", arguments=safe_arguments, duration_ms=self._elapsed(started), error_code="TOOL_EXECUTION_FAILED", error_message="工具执行失败")

    @staticmethod
    def _elapsed(started: float) -> int:
        return max(0, round((time.perf_counter() - started) * 1000))


def _loads(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return fallback


def build_tool_registry(retrieval: MultiChannelRetrievalEngine | None) -> ToolRegistry:
    order_service = OrderService()

    def order_context(context: ToolContext, order_no: str) -> dict | None:
        try:
            return order_service.detail(context.db, context.owner_id, order_no)
        except AppError as exc:
            if exc.code == "ORDER_NOT_FOUND":
                return None
            raise

    async def knowledge_search(context: ToolContext, value: QueryInput) -> list[ToolEvidence]:
        if retrieval is None:
            rows = context.db.execute(
                select(KnowledgeChunk, KnowledgeDocument)
                .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
                .join(KnowledgeBase, KnowledgeBase.id == KnowledgeDocument.knowledge_base_id)
                .where(KnowledgeBase.owner_id == context.owner_id, KnowledgeChunk.enabled.is_(True), KnowledgeDocument.enabled.is_(True), KnowledgeChunk.content.ilike(f"%{value.query}%"))
                .limit(value.limit)
            ).all()
            return [_document_evidence(chunk, document) for chunk, document in rows]
        response = await retrieval.retrieve(RetrievalRequest(
            query=value.query,
            knowledge_base_ids=tuple(str(item) for item in context.knowledge_base_ids),
            candidate_limit=max(20, value.limit), context_limit=value.limit,
            metadata={"user_id": context.owner_id},
        ))
        return [ToolEvidence(id=item.id, content=item.content, source=item.source or "knowledge", score=item.score, provenance=str(item.metadata.get("provenance", "source")), metadata=item.metadata) for item in response.results]

    async def knowledge_document(context: ToolContext, value: RecordInput) -> list[ToolEvidence]:
        document = context.db.scalar(select(KnowledgeDocument).join(KnowledgeBase).where(KnowledgeDocument.id == value.record_id, KnowledgeBase.owner_id == context.owner_id))
        if document is None:
            return []
        chunks = list(context.db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id, KnowledgeChunk.enabled.is_(True)).order_by(KnowledgeChunk.position).limit(8)))
        content = "\n".join(chunk.content for chunk in chunks)
        return [ToolEvidence(id=f"document:{document.id}", content=content or document.filename, source=document.filename, provenance=document.content_origin, metadata=_document_metadata(document))]

    async def association_rules(context: ToolContext, value: AssociationInput) -> list[ToolEvidence]:
        left = aliased(Product); right = aliased(Product)
        query = select(AssociationRule, left.name, right.name).join(left, left.id == AssociationRule.antecedent_product_id).join(right, right.id == AssociationRule.consequent_product_id).where(AssociationRule.owner_id == context.owner_id, AssociationRule.lift >= value.min_lift)
        if value.query:
            query = query.where(or_(left.name.ilike(f"%{value.query}%"), right.name.ilike(f"%{value.query}%")))
        rows = context.db.execute(query.order_by(AssociationRule.lift.desc()).limit(value.limit)).all()
        return [ToolEvidence(id=f"association:{rule.id}", content=f"{left_name} → {right_name}：共同出现 {rule.cooccurrence_count} 次，支持度 {rule.support:.3f}，置信度 {rule.confidence:.3f}，提升度 {rule.lift:.2f}。", source="commerce_association_rules", provenance="derived", metadata={"rule_id": rule.id, "lift": rule.lift, "support": rule.support}) for rule, left_name, right_name in rows]

    async def product_metrics(context: ToolContext, value: ProductMetricsInput) -> list[ToolEvidence]:
        query = select(Product.id, Product.name, Product.category, func.count(BasketItem.id), func.coalesce(func.sum(BasketItem.quantity), 0)).outerjoin(BasketItem, BasketItem.product_id == Product.id).where(Product.owner_id == context.owner_id).group_by(Product.id, Product.name, Product.category)
        if value.query:
            query = query.where(or_(Product.name.ilike(f"%{value.query}%"), Product.category.ilike(f"%{value.query}%")))
        rows = context.db.execute(query.order_by(func.count(BasketItem.id).desc()).limit(value.limit)).all()
        return [ToolEvidence(id=f"product:{product_id}", content=f"商品 {name}（{category}）：出现在 {line_count} 条交易明细中，记录数量合计 {quantity}。", source="commerce_product_metrics", provenance="observed+derived", metadata={"product_id": product_id, "line_count": line_count}) for product_id, name, category, line_count, quantity in rows]

    async def support_cases(context: ToolContext, value: SupportSearchInput) -> list[ToolEvidence]:
        query = select(SupportCase).where(SupportCase.owner_id == context.owner_id)
        if value.query:
            query = query.where(or_(SupportCase.subject.ilike(f"%{value.query}%"), SupportCase.case_key.ilike(f"%{value.query}%"), SupportCase.labels_json.ilike(f"%{value.query}%")))
        if value.status:
            query = query.where(SupportCase.status == value.status)
        rows = list(context.db.scalars(query.order_by(SupportCase.updated_at.desc()).limit(value.limit)))
        return [ToolEvidence(id=f"support-case:{item.id}", content=f"案例 {item.case_key}：{item.subject}；状态 {item.status}，优先级 {item.priority}。", source="support_cases", provenance="synthetic" if item.is_demo else "observed", metadata={"case_id": item.id, "status": item.status, "is_demo": item.is_demo}) for item in rows]

    async def quality_metrics(context: ToolContext, value: QueryInput) -> list[ToolEvidence]:
        rows = context.db.execute(select(SupportQualityLabel.verdict, SupportQualityLabel.failure_category, func.count()).where(SupportQualityLabel.owner_id == context.owner_id).group_by(SupportQualityLabel.verdict, SupportQualityLabel.failure_category)).all()
        if not rows:
            return []
        summary = "，".join(f"{verdict}/{category or '无'}={count}" for verdict, category, count in rows)
        return [ToolEvidence(id="support-quality:overview", content=f"客服质检分布：{summary}。演示案例指标不代表生产经营结果。", source="support_quality_labels", provenance="derived", metadata={"groups": len(rows)})]

    async def knowledge_gaps(context: ToolContext, value: QueryInput) -> list[ToolEvidence]:
        query = select(KnowledgeGap).where(KnowledgeGap.owner_id == context.owner_id, KnowledgeGap.status == "open")
        if value.query:
            query = query.where(or_(KnowledgeGap.title.ilike(f"%{value.query}%"), KnowledgeGap.category.ilike(f"%{value.query}%")))
        rows = list(context.db.scalars(query.order_by(KnowledgeGap.occurrence_count.desc()).limit(value.limit)))
        return [ToolEvidence(id=f"knowledge-gap:{item.id}", content=f"知识缺口：{item.title}；类别 {item.category}，严重度 {item.severity}，出现 {item.occurrence_count} 次。", source="knowledge_gaps", provenance="derived", metadata={"gap_id": item.id, "severity": item.severity}) for item in rows]

    async def get_order(context: ToolContext, value: OrderLookupInput) -> list[ToolEvidence]:
        detail = order_context(context, value.order_no)
        if detail is None:
            return []
        amount = detail["amount"]
        return [ToolEvidence(
            id=f"order:{detail['id']}",
            content=(
                f"订单 {detail['orderNo']} 状态为 {detail['status']}，"
                f"金额 {amount['minor']} {amount['currency']}（最小货币单位），"
                f"共 {len(detail['items'])} 项商品。"
            ),
            source="orders",
            provenance=detail["provenance"],
            metadata={
                "factType": "order",
                "orderId": detail["id"],
                "orderNo": detail["orderNo"],
                "status": detail["status"],
                "amount": amount,
                "items": detail["items"],
                "lineage": detail["lineage"],
            },
        )]

    async def get_delivery_status(context: ToolContext, value: OrderLookupInput) -> list[ToolEvidence]:
        detail = order_context(context, value.order_no)
        fulfillment = detail.get("fulfillment") if detail else None
        if fulfillment is None:
            return []
        return [ToolEvidence(
            id=f"fulfillment:{fulfillment['id']}",
            content=(
                f"订单 {detail['orderNo']} 配送状态为 {fulfillment['status']}；"
                f"预计送达 {fulfillment['estimatedDeliveryAt'] or '未知'}，"
                f"实际送达 {fulfillment['deliveredAt'] or '尚未送达'}。"
            ),
            source="fulfillments",
            provenance=detail["provenance"],
            metadata={"factType": "delivery", "orderNo": detail["orderNo"], **fulfillment},
        )]

    async def get_refund_status(context: ToolContext, value: OrderLookupInput) -> list[ToolEvidence]:
        detail = order_context(context, value.order_no)
        refund = detail.get("refund") if detail else None
        if refund is None:
            return []
        return [ToolEvidence(
            id=f"refund:{refund['id']}",
            content=(
                f"订单 {detail['orderNo']} 退款状态为 {refund['status']}，"
                f"退款金额 {refund['amountMinor']}（最小货币单位）。"
            ),
            source="refunds",
            provenance=detail["provenance"],
            metadata={"factType": "refund", "orderNo": detail["orderNo"], **refund},
        )]

    async def get_customer_history(context: ToolContext, value: OrderLookupInput) -> list[ToolEvidence]:
        detail = order_context(context, value.order_no)
        customer = detail.get("customer") if detail else None
        if customer is None:
            return []
        return [ToolEvidence(
            id=f"customer:{customer['id']}",
            content=(
                f"顾客 {customer['displayName']} 历史订单 {customer['orderCount']} 笔，"
                f"退款 {customer['refundCount']} 笔。"
            ),
            source="customer_snapshots",
            provenance="synthetic" if customer["isDemo"] else "observed",
            metadata={"factType": "customer_history", "orderNo": detail["orderNo"], **customer},
        )]

    tools = [
        AgentTool("knowledge.search", "检索当前商家的政策、SOP 与规则证据", QueryInput, knowledge_search),
        AgentTool("knowledge.get_document", "读取当前商家指定知识文档", RecordInput, knowledge_document),
        AgentTool("commerce.search_association_rules", "查询商品关联规则", AssociationInput, association_rules),
        AgentTool("commerce.get_product_metrics", "查询商品交易覆盖指标", ProductMetricsInput, product_metrics),
        AgentTool("commerce.get_order", "按订单号查询订单与商品事实", OrderLookupInput, get_order),
        AgentTool("commerce.get_delivery_status", "按订单号查询履约与配送事实", OrderLookupInput, get_delivery_status),
        AgentTool("commerce.get_refund_status", "按订单号查询退款事实", OrderLookupInput, get_refund_status),
        AgentTool("commerce.get_customer_history", "按订单号查询顾客历史快照", OrderLookupInput, get_customer_history),
        AgentTool("support.search_cases", "检索客服案例", SupportSearchInput, support_cases),
        AgentTool("support.get_quality_metrics", "查询客服质检指标", QueryInput, quality_metrics),
        AgentTool("support.get_knowledge_gaps", "查询待解决知识缺口", QueryInput, knowledge_gaps),
    ]
    return ToolRegistry(tools, aliases={
        "knowledge_search": "knowledge.search",
        "commerce_data": "commerce.get_product_metrics",
        "support_cases": "support.search_cases",
    })


def _document_metadata(document: KnowledgeDocument) -> dict[str, Any]:
    return {
        "document_id": document.id,
        "publisher": document.source_publisher,
        "canonical_url": document.source_url,
        "retrieval_date": document.source_retrieved_at.isoformat() if document.source_retrieved_at else None,
        "applicability": _loads(document.applicability_json, []),
        "exclusions": _loads(document.exclusions_json, []),
        "review_status": document.review_status,
    }


def _document_evidence(chunk: KnowledgeChunk, document: KnowledgeDocument) -> ToolEvidence:
    return ToolEvidence(id=f"chunk:{chunk.id}", content=chunk.content, source=document.filename, provenance=document.content_origin, metadata={**_document_metadata(document), "chunk_id": chunk.id})
