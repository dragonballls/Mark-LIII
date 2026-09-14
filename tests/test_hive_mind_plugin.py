from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_PATH = ROOT / "plugins" / "hive_mind.py"


def load_plugin():
    spec = importlib.util.spec_from_file_location("plugins.hive_mind_test", PLUGIN_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hive_mind_is_a_real_plugin_with_manager_settings():
    plugin = load_plugin()
    assert plugin.PLUGIN["name"] == "hive_mind"
    assert plugin.PLUGIN["parameters"]["required"] == ["goal"]
    assert plugin.PLUGIN_SETTINGS["namespace"] == "hive_mind"
    keys = {field["key"] for field in plugin.PLUGIN_SETTINGS["fields"]}
    assert {"enabled", "max_agents", "synthesize"} <= keys


def test_hive_mind_plugin_delegates_to_core_hive(monkeypatch):
    plugin = load_plugin()
    monkeypatch.setattr(plugin, "_setting", lambda key, default: default)

    class FakeResult:
        pass

    monkeypatch.setattr(plugin, "run_hive", lambda goal, max_agents, synthesize: FakeResult())
    monkeypatch.setattr(plugin, "summarize", lambda result: "Hive mind test result")

    assert plugin.run({"goal": "test", "max_agents": 3, "synthesize": False}) == "Hive mind test result"
