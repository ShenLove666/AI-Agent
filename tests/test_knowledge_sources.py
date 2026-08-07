from __future__ import annotations

from pathlib import Path

from app.modules.demo.catalog import load_demo_catalog


def test_knowledge_corpus_has_authoritative_metadata_and_original_summaries():
    root = Path(__file__).parents[1] / "resources/demo"
    catalog = load_demo_catalog(root)
    assert len(catalog.documents) >= 12
    public = [item for item in catalog.documents if item.content_origin == "public_summary"]
    assert len(public) >= 10
    assert all(item.source_url and item.source_publisher and item.source_retrieved_at for item in public)
    for item in catalog.documents:
        text = (root / item.local_path).read_text(encoding="utf-8")
        assert len(text) >= 300
        if item.content_origin == "public_summary":
            assert "原创" in text and "官方" in text
