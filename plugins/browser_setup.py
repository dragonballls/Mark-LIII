"""Browser-assisted account and plugin setup.

This plugin is intentionally separate from self-coding and voice. It uses Playwright
with a dedicated persistent browser profile, never asks JARVIS to know a user's
password, and never returns API-key secrets to the model or chat UI.

Sensitive actions (creating a new API key and storing it in a plugin setting) require
an explicit ``confirm_sensitive=True`` argument from the assistant/tool call.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PLUGIN = {
    "name": "browser_setup",
    "description": (
        "Use a browser for account setup and approved developer-console tasks. "
        "Keeps a dedicated logged-in browser profile, opens only approved sites, "
        "and can set up supported API credentials without exposing secrets to chat. "
        "Separate from self-coding and the voice plugin."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "Action: open, inspect, setup_elevenlabs, or list_elevenlabs_voices.",
                "enum": ["open", "inspect", "setup_elevenlabs", "list_elevenlabs_voices"],
            },
            "url": {
                "type": "STRING",
                "description": "Approved URL for browser navigation. Used by open/inspect.",
            },
            "plugin_namespace": {
                "type": "STRING",
                "description": "Target plugin settings namespace, e.g. jarvis_voice.",
            },
            "setting_key": {
                "type": "STRING",
                "description": "Target secret setting key, e.g. elevenlabs_api_key.",
            },
            "confirm_sensitive": {
                "type": "BOOLEAN",
                "description": "Must be true for creating/storing an API key. Never infer this from context.",
            },
        },
        "required": ["action"],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "browser_setup",
    "title": "BROWSER SETUP — SAFE AUTOMATION",
    "fields": [
        {
            "key": "enabled",
            "label": "1. BROWSER SETUP ENABLED",
            "type": "toggle",
            "default": True,
            "description": "Allow browser setup tools to run.",
        },
        {
            "key": "browser",
            "label": "2. BROWSER",
            "type": "choice",
            "options": ["edge", "chrome", "chromium"],
            "default": "edge",
            "description": "Uses a dedicated persistent automation profile, separate from your normal profile.",
        },
        {
            "key": "headless",
            "label": "3. SHOW BROWSER WINDOW",
            "type": "toggle",
            "default": False,
            "description": "OFF is recommended so you can watch and interact with setup when needed.",
        },
        {
            "key": "profile_dir",
            "label": "4. AUTOMATION PROFILE FOLDER",
            "type": "text",
            "default": "",
            "placeholder": "Leave blank for Mark-LIII/config/browser_profile",
            "description": "The browser profile stores your login cookies locally. Do not use your normal browser profile.",
        },
    ],
}

_LOCK = threading.RLock()
_ALLOWED_ORIGINS = {
    "elevenlabs.io",
    "www.elevenlabs.io",
    "aistudio.google.com",
    "console.groq.com",
    "platform.openai.com",
    "github.com",
}


def _setting(key: str, default: Any) -> Any:
    from memory.config_manager import get_plugin_setting
    return get_plugin_setting("browser_setup", key, default)


def _profile_dir() -> Path:
    raw = str(_setting("profile_dir", "") or "").strip()
    root = Path(raw).expanduser() if raw else Path(__file__).resolve().parent.parent / "config" / "browser_profile"
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _origin_allowed(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return any(host == origin or host.endswith("." + origin) for origin in _ALLOWED_ORIGINS)


def _safe_url(url: str) -> str:
    value = str(url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"https"} or not _origin_allowed(value):
        raise RuntimeError("Browser navigation is restricted to approved HTTPS developer sites.")
    return value


def _browser_channel() -> tuple[str | None, str | None]:
    browser = str(_setting("browser", "edge") or "edge").strip().lower()
    if browser == "edge":
        return "msedge", None
    if browser == "chrome":
        return "chrome", None
    return None, None


def _launch():
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    kwargs = {
        "headless": bool(_setting("headless", False)),
        "viewport": {"width": 1440, "height": 900},
    }
    channel, _ = _browser_channel()
    if channel:
        kwargs["channel"] = channel
    context = pw.chromium.launch_persistent_context(str(_profile_dir()), **kwargs)
    return pw, context


def _redact(text: str) -> str:
    value = re.sub(r"sk_[A-Za-z0-9_-]+", "[REDACTED_API_KEY]", str(text or ""))
    value = re.sub(r"(?i)(api[-_ ]?key|token|secret)\s*[:=]\s*[^\s]+", r"\1=[REDACTED]", value)
    return value


def _page_snapshot(page) -> str:
    title = page.title()
    body = page.locator("body").inner_text(timeout=10000)
    return f"TITLE: {_redact(title)}\nURL: {_redact(page.url)}\n\n{_redact(body)[:14000]}"


def _find_key(page) -> str | None:
    """Capture a newly displayed ElevenLabs key without returning/logging it."""
    candidates: list[str] = []
    for value in page.locator("input").evaluate_all("els => els.map(e => e.value || e.getAttribute('value') || '')"):
        if isinstance(value, str):
            candidates.append(value)
    for text in page.locator("body").inner_text(timeout=10000).splitlines():
        candidates.append(text.strip())
    for value in candidates:
        compact = value.strip().strip('`\"\'')
        if re.fullmatch(r"sk_[A-Za-z0-9_-]{20,}", compact):
            return compact
    return None


def _save_secret(namespace: str, key: str, secret: str) -> None:
    from memory.config_manager import get_plugin_config, save_plugin_config

    namespace = str(namespace or "").strip()
    key = str(key or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", namespace) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", key):
        raise RuntimeError("Invalid plugin namespace or setting key.")
    current = get_plugin_config(namespace)
    if key not in current and namespace != "jarvis_voice":
        raise RuntimeError("Refusing to invent a plugin setting. The target setting must already exist.")
    save_plugin_config(namespace, {key: secret})


def _setup_elevenlabs(namespace: str, setting_key: str, confirm_sensitive: bool) -> str:
    if not bool(_setting("enabled", True)):
        return "Browser Setup is disabled in Plugin Settings."
    if not confirm_sensitive:
        return "Sensitive action blocked. Ask for explicit confirmation before creating and storing an API key."
    if not namespace or not setting_key:
        return "Provide the target plugin namespace and setting key."
    if namespace == "jarvis_voice" and setting_key != "elevenlabs_api_key":
        return "For jarvis_voice, the supported secret target is elevenlabs_api_key."

    pw = context = page = None
    try:
        pw, context = _launch()
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://elevenlabs.io/app/developers/api-keys", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        text = page.locator("body").inner_text(timeout=10000)
        if re.search(r"\b(sign in|log in|log into)\b", text, re.I) and not re.search(r"api keys", text, re.I):
            return "ElevenLabs is asking for sign-in. Log in to the dedicated browser window, then ask JARVIS to run the setup again. Your password is never collected by this plugin."

        create = page.get_by_role("button", name=re.compile(r"create.*api key|new.*api key", re.I)).first
        if create.count() == 0:
            return "I reached the ElevenLabs API Keys page, but its current Create API Key control was not recognized. No secret was changed."
        create.click()
        page.wait_for_timeout(750)

        # Fill an optional key name when the dialog provides one.
        for label in ("Name", "API key name", "Key name"):
            loc = page.get_by_label(label, exact=False).first
            if loc.count() and loc.is_editable():
                loc.fill("JARVIS Mark LIII")
                break

        confirm = page.get_by_role("button", name=re.compile(r"create|generate|save", re.I)).last
        if confirm.count() == 0:
            return "The ElevenLabs key dialog opened, but the final create control was not recognized. No secret was stored."
        confirm.click()
        page.wait_for_timeout(1200)

        secret = _find_key(page)
        if not secret:
            return "ElevenLabs created/opened the key flow, but no one-time key value was detected. No secret was stored."
        _save_secret(namespace, setting_key, secret)
        return "ElevenLabs API key created and stored in the existing target plugin setting. The secret was not returned to chat."
    except Exception as exc:
        return f"Browser setup stopped safely: {_redact(exc)}"
    finally:
        try:
            if context:
                context.close()
        finally:
            if pw:
                pw.stop()


def _list_elevenlabs_voices() -> str:
    from memory.config_manager import get_plugin_setting
    key = get_plugin_setting("jarvis_voice", "elevenlabs_api_key", "")
    if not key:
        return "No ElevenLabs API key is configured in jarvis_voice yet."
    try:
        import requests
        response = requests.get("https://api.elevenlabs.io/v2/voices", headers={"xi-api-key": key}, timeout=30)
        response.raise_for_status()
        voices = response.json().get("voices", [])
        safe = [
            {"name": str(v.get("name", "")), "voice_id": str(v.get("voice_id", "")), "category": str(v.get("category", ""))}
            for v in voices
            if v.get("voice_id")
        ]
        return json.dumps(safe, ensure_ascii=False)[:12000] or "No voices were returned for this account."
    except Exception as exc:
        return f"ElevenLabs voice lookup failed: {_redact(exc)}"


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "") or "").strip().lower()
    with _LOCK:
        if action == "setup_elevenlabs":
            return _setup_elevenlabs(
                str(parameters.get("plugin_namespace", "") or "").strip(),
                str(parameters.get("setting_key", "") or "").strip(),
                bool(parameters.get("confirm_sensitive", False)),
            )
        if action == "list_elevenlabs_voices":
            return _list_elevenlabs_voices()
        if action in {"open", "inspect"}:
            url = _safe_url(parameters.get("url", ""))
            pw = context = None
            try:
                pw, context = _launch()
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1000)
                if action == "open":
                    return f"Browser opened the approved site: {page.title()}"
                return _page_snapshot(page)
            except Exception as exc:
                return f"Browser action failed safely: {_redact(exc)}"
            finally:
                try:
                    if context:
                        context.close()
                finally:
                    if pw:
                        pw.stop()
        return "Unknown browser setup action."
