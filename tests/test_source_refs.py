from app.api.system import _source_ref


def test_internal_commerce_evidence_keeps_its_business_identity():
    source = _source_ref(
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
