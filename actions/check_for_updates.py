"""Action for checking the creator's upstream build on demand."""
from __future__ import annotations

from typing import Any

from core.self_updater import check_and_update


def check_for_updates(parameters: dict, player=None, speak=None, **_: Any) -> str:
    """Check FatihMakes/Mark-LIII main and safely apply a newer build."""
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
        "Check whether FatihMakes/Mark-LIII has a newer build and safely update JARVIS. "
        "Protect local changes, create a recovery point, validate the updated source, "
        "and restart only after a successful update."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {},
    },
    "handler": check_for_updates,
}
