from pathlib import Path

from app.modules.demo.catalog import load_demo_catalog


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_agent_evaluation_catalog_has_deterministic_coverage():
    first = load_demo_catalog(PROJECT_ROOT / "resources" / "demo")
    second = load_demo_catalog(PROJECT_ROOT / "resources" / "demo")
    assert len(first.evaluation_cases) == 50
    assert first.evaluation_cases == second.evaluation_cases
    categories = {item.category for item in first.evaluation_cases}
    assert {"commerce_analysis", "support_quality", "insufficient_evidence", "cancellation_limit", "fresh_boundary", "safety"} <= categories
    assert len({item.key for item in first.evaluation_cases}) == 50
    assert all(item.expected_points for item in first.evaluation_cases)
