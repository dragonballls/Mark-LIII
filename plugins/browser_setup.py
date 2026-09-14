"""Browser-assisted setup helper.

Separate from self-coding and the voice plugin. Uses a dedicated persistent
Playwright profile, restricts navigation to approved HTTPS developer sites,
and never captures, reads, stores, or transfers authentication secrets.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PLUGIN = {
    "name": "browser_setup",
    "description": "Dedicated browser helper for approved developer-console navigation and inspection. Authentication secrets are entered manually into plugin settings.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "open or inspect an approved developer site.", "enum": ["open", "inspect"]},
            "url": {"type": "STRING", "description": "Approved HTTPS developer-console URL."},
        },
        "required": ["action"],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "browser_setup",
    "title": "BROWSER SETUP — SAFE AUTOMATION",
    "fields": [
        {"key": "enabled", "label": "1. BROWSER SETUP ENABLED", "type": "toggle", "default": True, "description": "Allow browser setup tools to run."},
        {"key": "browser", "label": "2. BROWSER", "type": "choice", "options": ["edge", "chrome", "chromium"], "default": "edge", "description": "Uses a dedicated automation profile, never your normal profile."},
        {"key": "headless", "label": "3. SHOW BROWSER WINDOW", "type": "toggle", "default": False, "description": "ON lets you watch and interact with setup."},
        {"key": "profile_dir", "label": "4. AUTOMATION PROFILE FOLDER", "type": "text", "default": "", "placeholder": "Leave blank for Mark-LIII/config/browser_profile", "description": "Local dedicated browser profile."},
    ],
}

_LOCK = threading.RLock()
_ALLOWED_ORIGINS = {"elevenlabs.io", "aistudio.google.com", "console.groq.com", "platform.openai.com", "github.com"}


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
    if parsed.scheme != "https" or not _origin_allowed(value):
        raise RuntimeError("Navigation is restricted to approved HTTPS developer sites.")
    return value


def _launch():
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = str(_setting("browser", "edge") or "edge").strip().lower()
    kwargs = {"headless": bool(_setting("headless", False)), "viewport": {"width": 1440, "height": 900}}
    if browser == "edge":
        kwargs["channel"] = "msedge"
    elif browser == "chrome":
        kwargs["channel"] = "chrome"
    context = pw.chromium.launch_persistent_context(str(_profile_dir()), **kwargs)
    return pw, context


def _redact(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"\bsk_[A-Za-z0-9_-]{20,}\b", "[REDACTED]", value)
    return re.sub(r"(?i)(api[-_ ]?key|token|secret)\s*[:=]\s*[^\s]+", r"\1=[REDACTED]", value)


def run(parameters: dict, player=None, session_memory=None) -> str:
    if not bool(_setting("enabled", True)):
        return "Browser Setup is disabled in Plugin Settings."
    action = str(parameters.get("action", "") or "").strip().lower()
    if action not in {"open", "inspect"}:
        return "Use browser_setup with action open or inspect."
    try:
        url = _safe_url(parameters.get("url", ""))
        with _LOCK:
            pw, context = _launch()
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(800)
                if action == "open":
                    return f"Browser opened the approved site: {_redact(page.title())}"
                return f"TITLE: {_redact(page.title())}\nURL: {_redact(page.url)}\n\n{_redact(page.locator('body').inner_text(timeout=10000))[:14000]}"
            finally:
                context.close()
                pw.stop()
    except Exception as exc:
        return f"Browser setup stopped safely: {_redact(exc)}"
