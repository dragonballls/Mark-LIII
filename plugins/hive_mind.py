"""JARVIS Hive Mind plugin.

The hive is a standalone plugin: it is visible in Plugin Manager and can be
called by the live assistant without being coupled to the self-coding engine.
Actual orchestration remains in core.hive_mind so the plugin is only an adapter.
"""
from __future__ import annotations

from typing import Any

from core.hive_mind import run_hive, summarize


PLUGIN = {
    "name": "hive_mind",
    "description": (
        "Standalone JARVIS Hive Mind. Fans a goal out to explicitly configured hosted AI agents "
        "in parallel, isolates failures, and optionally synthesizes the reports. Supports Gemini, "
        "Anthropic, and OpenAI-compatible providers. Never installs a local LLM or performs "
        "external actions by itself."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "goal": {
                "type": "STRING",
                "description": "The problem or question for the hive to analyze.",
            },
            "max_agents": {
                "type": "INTEGER",
                "description": "Maximum number of configured agents to query (default 6).",
            },
            "synthesize": {
                "type": "BOOLEAN",
                "description": "Whether the hive should synthesize successful reports.",
            },
        },
        "required": ["goal"],
    },
}


PLUGIN_SETTINGS = {
    "namespace": "hive_mind",
    "title": "HIVE MIND",
    "fields": [
        {
            "key": "enabled",
            "label": "1. HIVE MIND ENABLED",
            "type": "toggle",
            "default": True,
            "description": "Allow JARVIS to use the standalone multi-agent hive.",
        },
        {
            "key": "max_agents",
            "label": "2. MAX AGENTS",
            "type": "text",
            "default": "6",
            "placeholder": "6",
            "description": "Maximum configured hosted agents used for one hive request.",
        },
        {
            "key": "synthesize",
            "label": "3. SYNTHESIZE REPORTS",
            "type": "toggle",
            "default": True,
            "description": "Ask a suitable lead agent to combine successful reports.",
        },
    ],
}


def _setting(key: str, default: Any) -> Any:
    from memory.config_manager import get_plugin_setting

    return get_plugin_setting("hive_mind", key, default)


def run(parameters: dict, player=None, session_memory=None) -> str:
    if not bool(_setting("enabled", True)):
        return "The Hive Mind plugin is disabled in Plugin Manager."

    goal = str(parameters.get("goal", "")).strip()
    if not goal:
        return "Hive Mind requires a goal."

    try:
        max_agents = int(parameters.get("max_agents", _setting("max_agents", 6)))
    except (TypeError, ValueError):
        max_agents = 6

    synthesize = bool(parameters.get("synthesize", _setting("synthesize", True)))
    result = run_hive(goal, max_agents=max_agents, synthesize=synthesize)
    text = summarize(result)

    if player:
        try:
            player.write_log("[Hive Mind] " + text.replace("\n", " | "))
        except Exception:
            pass
    return text
