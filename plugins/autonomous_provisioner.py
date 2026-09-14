"""JARVIS plugin for autonomous free-first provider provisioning."""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any

from core.autonomous_provisioner import provision_all, provider_status

PLUGIN = {
    "name": "autonomous_provisioner",
    "description": (
        "Autonomously audits and provisions supported free-first AI and voice providers. "
        "Uses existing credentials first, then an already-authorized browser session "
        "to complete normal provider key setup, stores credentials in the local vault, "
        "and fails over to another supported provider when necessary. It never bypasses MFA or CAPTCHA."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "provision or status",
                "enum": ["provision", "status"],
            },
            "browser_setup": {
                "type": "BOOLEAN",
                "description": "Allow use of the existing authorized browser setup session.",
            },
        },
        "required": ["action"],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "autonomous_provisioner",
    "title": "AUTONOMOUS PROVISIONER",
    "fields": [
        {"key": "enabled", "label": "1. AUTONOMOUS PROVISIONING ENABLED", "type": "toggle", "default": True, "description": "Let JARVIS automatically provision supported providers."},
        {"key": "browser_setup", "label": "2. USE AUTHORIZED BROWSER SESSION", "type": "toggle", "default": True, "description": "Allow provider dashboard setup through the existing authenticated browser profile."},
    ],
}

_MONITOR_STARTED = False
_MONITOR_LOCK = threading.Lock()


def _setting(key: str, default: Any) -> Any:
    from memory.config_manager import get_plugin_setting
    return get_plugin_setting("autonomous_provisioner", key, default)


def _background_provision() -> None:
    # Give the live session time to finish startup before touching a provider
    # dashboard. Retries are infrequent so a missing login never creates a loop.
    time.sleep(45)
    while True:
        try:
            if bool(_setting("enabled", True)):
                provision_all(
                    allow_browser=bool(_setting("browser_setup", True)),
                )
        except Exception:
            pass
        time.sleep(6 * 60 * 60)


def start_background_monitor() -> None:
    global _MONITOR_STARTED
    with _MONITOR_LOCK:
        if _MONITOR_STARTED:
            return
        _MONITOR_STARTED = True
        threading.Thread(
            target=_background_provision,
            daemon=True,
            name="JARVIS-Autonomous-Provisioner",
        ).start()


def _maybe_start_monitor() -> None:
    if os.getenv("MARK_DISABLE_AUTO_PROVISION") == "1":
        return
    argv0 = os.path.basename(sys.argv[0]).lower() if sys.argv else ""
    if argv0 in {"main.py", "mark-liii.exe", "jarvis.exe", "jarvis"}:
        start_background_monitor()


def run(parameters: dict, player=None, session_memory=None) -> str:
    if not bool(_setting("enabled", True)):
        return "Autonomous Provisioner is disabled in Plugin Settings."
    action = str(parameters.get("action", "status") or "status").strip().lower()
    if action == "status":
        rows = provider_status()
        ready = [r["provider"] for r in rows if r["configured"]]
        return "Provider status: " + (", ".join(ready) if ready else "no provider credential currently configured")
    if action != "provision":
        return "Use autonomous_provisioner with action provision or status."
    allow_browser = bool(parameters.get("browser_setup", _setting("browser_setup", True)))
    result = provision_all(allow_browser=allow_browser, logger=player.write_log if player else None)
    if result["status"] == "ready":
        ready = ", ".join(result["ready"])
        return f"Autonomous provisioning complete. Ready providers: {ready}. Credentials were stored securely on this device."
    return result["message"]


_maybe_start_monitor()
