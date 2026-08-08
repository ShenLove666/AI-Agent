from __future__ import annotations


_INTERNAL_SOURCE_NAMES = {
    "commerce_association_rules": "购物篮关联规则",
    "commerce_product_metrics": "商品交易指标",
    "support_cases": "客服案例",
    "support_quality_labels": "客服质检指标",
    "knowledge_gaps": "知识缺口",
    "orders": "订单事实",
    "fulfillments": "履约事实",
    "refunds": "退款事实",
    "customer_snapshots": "顾客历史快照",
}


def source_ref(item: dict, index: int) -> dict:
    metadata = item.get("metadata") or {}
    source_name = item.get("source") or ""
    if source_name in _INTERNAL_SOURCE_NAMES:
        return {
            "index": index,
            "docName": _INTERNAL_SOURCE_NAMES[source_name],
            "sourceType": "internal_data",
            "provenance": metadata.get("provenance") or item.get("provenance") or "derived",
            "excerpt": item.get("content") or "",
        }
    return {
        "index": index,
        "docId": str(metadata.get("document_id") or item.get("id") or ""),
        "docName": metadata.get("filename") or item.get("source") or "知识库文档",
        "excerpt": item.get("content") or "",
    }
