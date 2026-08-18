"""Testes da fundação de ramos (spec memory-branching, Tasks 1.1 e 1.2)."""

import pytest

from decisionssearch.domain.shared.branch import ALL_BRANCHES, DEFAULT_BRANCH
from decisionssearch.domain.shared.exceptions import MemoryServiceError
from decisionssearch.domain.memory.memory_item import MemoryItem
from decisionssearch.application.memory.branch_registry import BranchRegistry


def _item(**kw) -> MemoryItem:
    base = dict(memory_id="x", project="p", category="BusinessRule", title="t", summary="s")
    base.update(kw)
    return MemoryItem(**base)


# --- Registry (R1.1, R1.3, R1.4, R6.1) ---

def test_seed_branches_registered():
    reg = BranchRegistry()
    ids = {m.branch_id for m in reg.list()}
    assert {"semantic", "episodic", "procedural"} <= ids  # R1.4
    assert DEFAULT_BRANCH in ids


def test_register_makes_branch_recognized():
    reg = BranchRegistry(seed={})
    reg.register("code_blame", "blame de código")
    assert reg.is_registered("code_blame")  # R1.1


def test_register_duplicate_rejected():
    reg = BranchRegistry()
    with pytest.raises(MemoryServiceError):
        reg.register("semantic")  # R1.3


def test_register_empty_rejected():
    reg = BranchRegistry(seed={})
    with pytest.raises(MemoryServiceError):
        reg.register("   ")


def test_normalization_case_insensitive():
    reg = BranchRegistry(seed={})
    reg.register("  Code_Blame ")
    assert reg.is_registered("code_blame")


# --- Escopo (R3.3, R4.3, R5.1, R5.3, R7.1) ---

def test_require_unknown_branch_errors_with_name():
    reg = BranchRegistry()
    with pytest.raises(MemoryServiceError) as exc:
        reg.require("does_not_exist")  # R3.3 / R4.3
    assert "does_not_exist" in str(exc.value)


def test_resolve_scope_none_is_default():
    reg = BranchRegistry()
    assert reg.resolve_scope(None) == [DEFAULT_BRANCH]  # R7.1


def test_resolve_scope_all_returns_registered():
    reg = BranchRegistry()
    assert set(reg.resolve_scope(ALL_BRANCHES)) == {m.branch_id for m in reg.list()}  # R5.1


def test_resolve_scope_explicit_validates():
    reg = BranchRegistry()
    assert reg.resolve_scope(["semantic", "episodic"]) == ["semantic", "episodic"]  # R5.3
    with pytest.raises(MemoryServiceError):
        reg.resolve_scope(["semantic", "ghost"])  # R5.3 inválido


# --- Modelo (R1.2, R3.2) ---

def test_memory_item_defaults_to_semantic_branch():
    assert _item().branch == DEFAULT_BRANCH  # R3.2


def test_memory_item_normalizes_branch():
    assert _item(branch="  Episodic ").branch == "episodic"  # R1.2


def test_memory_item_empty_branch_falls_back_to_default():
    assert _item(branch="").branch == DEFAULT_BRANCH
