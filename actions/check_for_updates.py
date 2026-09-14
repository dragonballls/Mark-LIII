"""Action for checking the user's Mark-LIII build on demand."""
from __future__ import annotations

from typing import Any

from core.self_updater import check_and_update


def check_for_updates(parameters: dict, player=None, speak=None, **_: Any) -> str:
    """Check dragonballls/Mark-LIII main and safely apply a newer build."""
    def log(message: str) -> None:
        if player:
            try:
                player.write_log(message)
            except Exception:
                pass

    result = check_and_update(logger=log, restart=True)
    text = str(result.get("message", "Update check complete."))
    if speak:
        try:
            speak(text)
        except Exception:
            pass
    return text


TOOL = {
    "name": "check_for_updates",
    "description": (
        "Check whether dragonballls/Mark-LIII main has a newer build and safely update JARVIS. "
        "Protect local changes, create a recovery point, validate the source, synchronize "
        "requirements when needed, and restart only after the update succeeds."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {},
    },
    "handler": check_for_updates,
}
