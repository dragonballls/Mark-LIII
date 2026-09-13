"""Action that reports currently discoverable hosted free AI options."""
from __future__ import annotations

from typing import Any

from core.free_ai_catalog import compact_text, discover


def discover_free_ai(parameters: dict, player=None, speak=None, **_: Any) -> str:
    """Discover hosted free/zero-priced AI options without changing the application UI."""
    snapshot = discover()
    text = compact_text(snapshot)
    if player:
        try:
            player.write_log("[AI Discovery] refreshed hosted free AI catalog")
            player.write_log(text)
        except Exception:
            pass
    if speak:
        try:
            speak("I have refreshed the available hosted free AI options, sir.")
        except Exception:
            pass
    return text


TOOL = {
    "name": "discover_free_ai",
    "description": (
        "Discovers currently available zero-priced hosted AI model options. "
        "It does not install local models, launch computer-use agents, modify the UI, "
        "or change the assistant's existing runtime path."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {},
    },
    "handler": discover_free_ai,
}
