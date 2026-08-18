from decisionssearch.interfaces.mcp.prompts import register_prompts
from decisionssearch.interfaces.mcp.mcp_compat import FastMCP


def _get_prompt_names():
    app = FastMCP("test")
    register_prompts(app)
    return list(app._prompt_manager._prompts.keys())


def test_extract_architectural_decisions_prompt_exists():
    assert "extract_architectural_decisions" in _get_prompt_names()


def test_reflect_on_task_prompt_exists():
    assert "reflect_on_task" in _get_prompt_names()


def test_post_commit_memory_check_prompt_exists():
    assert "post_commit_memory_check" in _get_prompt_names()


def test_merge_memories_prompt_exists():
    assert "merge_memories" in _get_prompt_names()


def test_classify_memory_type_prompt_exists():
    assert "classify_memory_type" in _get_prompt_names()


def test_extract_design_rules_prompt_exists():
    assert "extract_design_rules" in _get_prompt_names()
