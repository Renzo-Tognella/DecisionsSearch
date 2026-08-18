from __future__ import annotations

import os
import yaml
from decisionssearch.infrastructure.config.config_loader import load_config, DecisionsSearchConfig, _resolve_env


class TestConfigLoader:
    def test_load_defaults(self, tmp_path):
        cfg = load_config(str(tmp_path / "nonexistent.yaml"))
        assert cfg.mode == "light"
        assert cfg.agent_provider == "opencode"
        assert cfg.safety["min_confidence"] == 0.7

    def test_load_from_file(self, tmp_path):
        cfg_path = tmp_path / "decisionssearch.yaml"
        cfg_path.write_text(yaml.dump({
            "mode": "full",
            "agent": {"provider": "claude", "claude": {"api_key": "sk-test-123"}},
        }))
        cfg = load_config(str(cfg_path))
        assert cfg.mode == "full"
        assert cfg.agent_provider == "claude"
        assert cfg.agent_api_key() == "sk-test-123"

    def test_env_var_resolution(self):
        os.environ["_TEST_CFG_KEY"] = "resolved-value"
        result = _resolve_env("prefix-${_TEST_CFG_KEY}-suffix")
        assert result == "prefix-resolved-value-suffix"
        del os.environ["_TEST_CFG_KEY"]

    def test_env_var_with_default(self):
        result = _resolve_env("${_MISSING_VAR__X:fallback}")
        assert result == "fallback"

    def test_agent_api_key_from_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "env-key-123")
        cfg_path = tmp_path / "decisionssearch.yaml"
        cfg_path.write_text(yaml.dump({"agent": {"provider": "codex", "codex": {"api_key": ""}}}))
        cfg = load_config(str(cfg_path))
        assert cfg.agent_api_key() == "env-key-123"

    def test_openrouter_agent_api_key_from_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env")
        cfg_path = tmp_path / "decisionssearch.yaml"
        cfg_path.write_text(yaml.dump({"agent": {"provider": "openrouter"}}))
        cfg = load_config(str(cfg_path))
        assert cfg.agent_api_key() == "sk-or-env"

    def test_nested_get(self):
        cfg = DecisionsSearchConfig({"a": {"b": {"c": 42}}})
        assert cfg.get("a", "b", "c") == 42
        assert cfg.get("a", "b", "missing", default="nope") == "nope"

    def test_notifications_config(self, tmp_path):
        cfg_path = tmp_path / "decisionssearch.yaml"
        cfg_path.write_text(yaml.dump({
            "notifications": {"slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/test"}},
        }))
        cfg = load_config(str(cfg_path))
        assert cfg.notifications["slack"]["enabled"] is True

    def test_safety_config(self, tmp_path):
        cfg_path = tmp_path / "decisionssearch.yaml"
        cfg_path.write_text(yaml.dump({
            "safety": {"min_confidence": 0.9, "max_auto_fixes_per_hour": 5},
        }))
        cfg = load_config(str(cfg_path))
        assert cfg.safety["min_confidence"] == 0.9
        assert cfg.safety["max_auto_fixes_per_hour"] == 5

    def test_as_dict(self):
        cfg = DecisionsSearchConfig({"mode": "light"})
        d = cfg.as_dict()
        assert isinstance(d, dict)
        assert d["mode"] == "light"
