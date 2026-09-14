"""Plugin settings and auto-configuration for native Opera GX support.

The actual browser control remains in actions/opera_gx.py. This plugin only
exposes settings and a safe one-click detector so Opera GX appears in Plugin
Settings without requiring a manual executable path.

The plugin identifier intentionally differs from the native ``opera_gx`` core
tool name. Its settings namespace is also distinct so the settings section
cannot be filtered as a duplicate core-tool namespace; auto-configuration
writes the native ``opera_gx`` settings consumed by actions/opera_gx.py.
"""
from __future__ import annotations

from pathlib import Path

PLUGIN = {
    "name": "opera_gx_settings",
    "description": (
        "Native Opera GX integration settings. Opera GX is detected automatically and uses the user's normal browser profile. "
        "Plugin Settings provides automatic detection and configuration for the native Opera GX tool."
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
            return False, "Opera GX was not found. The native integration will keep auto-detecting it on future checks."

        resolved = str(Path(executable).resolve())
        save_plugin_config("opera_gx", {"enabled": True, "executable_path": resolved})
        save_plugin_config("opera_gx_settings", {"enabled": True, "executable_path": resolved})
        return True, f"Opera GX configured automatically: {Path(executable).name}"
    except Exception as exc:
        return False, f"Opera GX auto-configuration failed safely: {exc}"


PLUGIN_SETTINGS = {
    "namespace": "opera_gx_settings",
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
            "description": "Filled automatically when AUTO-CONFIGURE OPERA GX is pressed.",
        },
    ],
    "action": {"label": "▸ AUTO-CONFIGURE OPERA GX", "run": _auto_configure},
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    return "Opera GX settings are managed automatically. Use the native Opera GX action to open or search in the browser."
