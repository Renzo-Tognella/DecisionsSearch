import json
from pathlib import Path

GOLDEN_PATH = Path(__file__).parents[1] / "golden" / "queries.jsonl"


def test_golden_dataset_is_valid_jsonl():
    assert GOLDEN_PATH.exists()
    lines = GOLDEN_PATH.read_text().strip().splitlines()
    assert len(lines) >= 5
    for line in lines:
        entry = json.loads(line)
        assert "query" in entry
        assert "project" in entry
        assert "description" in entry


def test_golden_dataset_has_required_fields():
    lines = GOLDEN_PATH.read_text().strip().splitlines()
    for line in lines:
        entry = json.loads(line)
        assert isinstance(entry["query"], str)
        assert isinstance(entry["project"], str)
        assert isinstance(entry["description"], str)


def test_golden_dataset_covers_all_categories():
    lines = GOLDEN_PATH.read_text().strip().splitlines()
    categories = set()
    for line in lines:
        entry = json.loads(line)
        if entry.get("expected_category"):
            categories.add(entry["expected_category"])
    assert "DesignRule" in categories
    assert "ArchitecturalDecision" in categories
    assert "BusinessRule" in categories
    assert "DesignPattern" in categories
