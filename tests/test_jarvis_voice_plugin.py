from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_PATH = ROOT / "plugins" / "jarvis_voice.py"


def load_plugin():
    spec = importlib.util.spec_from_file_location("plugins.jarvis_voice_test", PLUGIN_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_voice_plugin_metadata_and_settings():
    plugin = load_plugin()
    assert plugin.PLUGIN["name"] == "jarvis_voice"
    assert plugin.PLUGIN["parameters"]["required"] == ["text"]
    assert plugin.PLUGIN_SETTINGS["namespace"] == "jarvis_voice"
    keys = {field["key"] for field in plugin.PLUGIN_SETTINGS["fields"]}
    assert {"enabled", "engine", "edge_voice", "edge_rate", "edge_pitch", "elevenlabs_api_key", "elevenlabs_voice_id", "volume"} <= keys


def test_voice_plugin_has_no_self_coding_dependency():
    source = PLUGIN_PATH.read_text(encoding="utf-8")
    assert "self_coding_engine" not in source
    assert "coding" not in source.lower()
    assert "agent.core" not in source
    assert "desktop" not in source.lower()
