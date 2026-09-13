"""Action that reports currently discoverable free AI engines."""
from __future__ import annotations

from typing import Any

from core.free_ai_catalog import compact_text, discover


def discover_free_ai(parameters: dict, player=None, speak=None, **_: Any) -> str:
    """Discover free/zero-priced AI options without changing the application UI."""
    snapshot = discover()
    text = compact_text(snapshot)
    if player:
        try:
            player.write_log("[AI Discovery] refreshed free AI catalog")
            player.write_log(text)
        except Exception:
            pass
    if speak:
        try:
            speak("I have refreshed the available free AI options, sir.")
        except Exception:
            pass
    return text


TOOL = {
    "name": "discover_free_ai",
    "description": (
        "Discovers currently available zero-priced hosted model options and free/open-source "
        "coding engines. Refreshes live information without installing software or changing the UI."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {},
    },
    "handler": discover_free_ai,
}
