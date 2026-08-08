import json
from types import SimpleNamespace

from app.api.conversations import serialize_message
from app.api.source_refs import source_ref


def test_internal_commerce_evidence_keeps_its_business_identity():
    source = source_ref(
        {
            "id": "association:7",
            "source": "commerce_association_rules",
            "content": "牛肉 → 根茎类蔬菜：提升度 3.04。",
            "metadata": {"rule_id": 7, "provenance": "derived"},
        },
        1,
    )

    assert source == {
        "index": 1,
        "docName": "购物篮关联规则",
        "sourceType": "internal_data",
        "provenance": "derived",
        "excerpt": "牛肉 → 根茎类蔬菜：提升度 3.04。",
    }


def test_persisted_message_normalizes_internal_sources():
    message = SimpleNamespace(
        id=1,
        conversation_id="c1",
        turn_id=1,
        version=1,
        role="assistant",
        content="answer",
        citations_json=json.dumps(
            [{"id": "association:7", "source": "commerce_association_rules", "content": "rule", "metadata": {"provenance": "derived"}}]
        ),
        message_status="NORMAL",
        vote=None,
        thinking_content=None,
        thinking_duration_ms=None,
        recommended_questions_json=None,
        recommended_questions_status="NOT_REQUESTED",
        recommended_questions_error=None,
        created_at=SimpleNamespace(isoformat=lambda: "2026-08-08T00:00:00"),
    )

    assert serialize_message(message)["sources"][0]["docName"] == "购物篮关联规则"
