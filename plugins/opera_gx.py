"""Plugin settings and auto-configuration for native Opera GX support.

The actual browser control remains in actions/opera_gx.py. This plugin only
exposes optional settings and a safe one-click detector so Opera GX appears in
Plugin Settings without requiring a manual executable path.
"""
from __future__ import annotations

from pathlib import Path

PLUGIN = {
    "name": "opera_gx",
    "description": (
        "Native Opera GX integration. Opera GX is detected automatically and uses the user's normal browser profile. "
        "Plugin Settings provides an optional detected executable path and one-click auto-configuration."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {},
    },
}


def _auto_configure(values: dict):
    try:
        from memory.config_manager import save_plugin_config
        from actions.opera_gx import _find_opera_gx

        executable = _find_opera_gx()
        if not executable:
            return False, "Opera GX was not found. The integration will keep auto-detecting it on future checks."

        save_plugin_config(
            "opera_gx",
            {"enabled": True, "executable_path": str(Path(executable).resolve())},
        )
        return True, f"Opera GX configured automatically: {Path(executable).name}"
    except Exception as exc:
        return False, f"Opera GX auto-configuration failed safely: {exc}"


PLUGIN_SETTINGS = {
    "namespace": "opera_gx",
    "title": "OPERA GX — NATIVE BROWSER CONTROL",
    "fields": [
        {
            "key": "enabled",
            "label": "1. OPERA GX ENABLED",
            "type": "toggle",
            "default": True,
            "description": "Leave ON to allow native Opera GX control.",
        },
        {
            "key": "executable_path",
            "label": "2. OPERA GX EXECUTABLE",
            "type": "text",
            "default": "",
            "placeholder": "Leave blank — JARVIS detects Opera GX automatically",
            "description": "Optional detected path. Manual entry is not normally needed.",
        },
    ],
    "action": {"label": "▸ AUTO-CONFIGURE OPERA GX", "run": _auto_configure},
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    return "Opera GX settings are managed automatically. Use the native Opera GX action to open or search in the browser."
