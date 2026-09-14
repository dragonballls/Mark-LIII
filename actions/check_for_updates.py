"""Action for checking the user's Mark-LIII build on demand."""
from __future__ import annotations

import threading
import time
from typing import Any

from core.self_updater import check_and_update

_CHECK_LOCK = threading.Lock()
_LAST_CHECK_AT = 0.0
_LAST_RESULT: str | None = None
_MANUAL_CHECK_COOLDOWN = 8.0


def check_for_updates(parameters: dict, player=None, speak=None, **_: Any) -> str:
    """Check the official FatihMakes/Mark-LIII main branch and safely apply updates."""
    global _LAST_CHECK_AT, _LAST_RESULT

    now = time.monotonic()
    with _CHECK_LOCK:
        if _LAST_RESULT is not None and now - _LAST_CHECK_AT < _MANUAL_CHECK_COOLDOWN:
            return _LAST_RESULT

        def log(message: str) -> None:
            if player:
                try:
                    player.write_log(message)
                except Exception:
                    pass

        result = check_and_update(logger=log, restart=True)
        text = str(result.get("message", "Update check complete."))
        _LAST_CHECK_AT = time.monotonic()
        _LAST_RESULT = text

    if speak:
        try:
            speak(text)
        except Exception:
            pass
    return text


TOOL = {
    "name": "check_for_updates",
    "description": (
        "Check whether the official FatihMakes/Mark-LIII main branch has a newer build and safely update JARVIS. "
        "Protect local changes, create a recovery point, preserve custom commits, validate the source, "
        "synchronize requirements when needed, and restart only after the update succeeds. "
        "Repeated update requests received within a few seconds are de-duplicated."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {},
    },
    "handler": check_for_updates,
}
