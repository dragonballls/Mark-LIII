from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_prompt_is_english_only():
    prompt = (ROOT / "core" / "prompt.txt").read_text(encoding="utf-8")
    assert "LANGUAGE — ENGLISH ONLY:" in prompt
    assert "JARVIS speaks and writes English only." in prompt
    assert "the language of the user's MOST RECENT message" not in prompt
    assert "Translate and speak them naturally in the user's language." not in prompt


def test_native_voice_is_locked_to_charon():
    source = (ROOT / "memory" / "config_manager.py").read_text(encoding="utf-8")
    assert 'AVAILABLE_VOICES = ["Charon"]' in source
    assert "return DEFAULT_VOICE" in source
    assert "data[\"voice_name\"] = v if v in AVAILABLE_VOICES else DEFAULT_VOICE" not in source


def test_browser_setup_supports_guided_voice_setup_and_voice_id():
    source = (ROOT / "plugins" / "browser_setup.py").read_text(encoding="utf-8")
    assert "guide_voice_setup" in source
    assert "list_elevenlabs_voice_ids" in source
    assert "set_voice_id" in source
    assert "elevenlabs_api_key" not in source
    assert "authentication secrets" in source.lower()


def test_voice_plugin_remains_separate_from_browser_and_self_coding():
    source = (ROOT / "plugins" / "jarvis_voice.py").read_text(encoding="utf-8")
    assert "browser_setup" not in source
    assert "self_coding_engine" not in source
    assert "from agent." not in source
