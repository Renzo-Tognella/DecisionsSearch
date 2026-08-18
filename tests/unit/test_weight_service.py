from datetime import datetime, timedelta, timezone

from decisionssearch.application.governance.weight_service import WeightService


def test_effective_weight_in_range() -> None:
    service = WeightService()
    value = service.calculate_effective_weight(1.0, 1.0, 1.0, 1.0)
    assert 0.0 <= value <= 1.0


def test_decay_half_life_low_significance() -> None:
    service = WeightService()
    last_accessed = datetime.now(timezone.utc) - timedelta(days=30)
    decay = service.calculate_decay(significance=0.0, last_accessed_at=last_accessed)
    assert abs(decay - 0.5) < 0.02


def test_decay_high_significance_slower() -> None:
    service = WeightService()
    last_accessed = datetime.now(timezone.utc) - timedelta(days=90)
    low = service.calculate_decay(significance=0.0, last_accessed_at=last_accessed)
    high = service.calculate_decay(significance=1.0, last_accessed_at=last_accessed)
    assert high > low


def test_update_on_retrieval_caps_at_one() -> None:
    service = WeightService()
    updated = service.update_on_retrieval(current_usage=0.98, was_accepted=True)
    assert updated == 1.0


def test_priority_config_design_rule() -> None:
    service = WeightService()
    config = service.get_priority_config("DesignRule")
    assert config.alpha == 0.40


def test_reinforce_on_retrieval_accepted():
    ws = WeightService()
    w, u = ws.reinforce_on_retrieval(0.5, 0.3, was_accepted=True)
    assert w > 0.5
    assert u > 0.3


def test_reinforce_on_retrieval_rejected():
    ws = WeightService()
    w, u = ws.reinforce_on_retrieval(0.5, 0.3, was_accepted=False)
    assert w == 0.5
    assert u > 0.3


def test_reinforce_on_retrieval_capped_at_one():
    ws = WeightService()
    w, _ = ws.reinforce_on_retrieval(0.99, 0.3, was_accepted=True)
    assert w <= 1.0


def test_significance_for_category_varies_by_durability():
    # Q11: significance deixou de ser hardcoded 0.5 — varia por categoria.
    ws = WeightService()
    assert ws.significance_for_category("ArchitecturalDecision") == 0.9
    assert ws.significance_for_category("DesignRule") == 0.8
    assert ws.significance_for_category("BusinessRule") == 0.6
    assert ws.significance_for_category("Unknown") == 0.5


def test_significance_drives_decay_half_life():
    # Categorias mais significativas decaem mais devagar.
    ws = WeightService()
    last = datetime.now(timezone.utc) - timedelta(days=120)
    arch = ws.calculate_decay(ws.significance_for_category("ArchitecturalDecision"), last)
    biz = ws.calculate_decay(ws.significance_for_category("BusinessRule"), last)
    assert arch > biz


def test_effective_weight_uses_significance_for_decay() -> None:
    ws = WeightService()
    last = datetime.now(timezone.utc) - timedelta(days=120)
    low = ws.calculate_effective_weight(1.0, 1.0, 0.0, 0.0, last_accessed_at=last, significance=0.0)
    high = ws.calculate_effective_weight(1.0, 1.0, 0.0, 0.0, last_accessed_at=last, significance=1.0)
    assert high > low
