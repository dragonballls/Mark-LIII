"""Browser-assisted developer setup helper.

Separate from self-coding and the voice plugin. Uses a dedicated persistent
Playwright profile, restricts navigation to approved HTTPS developer sites,
and never captures, reads, stores, or transfers authentication secrets.

Non-secret account metadata such as an ElevenLabs Voice ID may be discovered
and, when explicitly supplied to ``set_voice_id``, written to the existing
jarvis_voice plugin setting.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PLUGIN = {
    "name": "browser_setup",
    "description": (
        "Guided browser helper for approved developer-console setup. It can open and inspect supported sites, "
        "discover non-secret metadata such as ElevenLabs Voice IDs, and explain exactly which Mark-LIII setting "
        "each value belongs in. Authentication secrets are never captured or returned to chat. Separate from self-coding and voice."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "open, inspect, guide_voice_setup, list_elevenlabs_voice_ids, or set_voice_id.",
                "enum": ["open", "inspect", "guide_voice_setup", "list_elevenlabs_voice_ids", "set_voice_id"],
            },
            "url": {
                "type": "STRING",
                "description": "Approved HTTPS developer-console URL for open/inspect.",
            },
            "voice_id": {
                "type": "STRING",
                "description": "Non-secret ElevenLabs Voice ID for set_voice_id.",
            },
        },
        "required": ["action"],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "browser_setup",
    "title": "BROWSER SETUP — GUIDED AUTOMATION",
    "fields": [
        {"key": "enabled", "label": "1. BROWSER SETUP ENABLED", "type": "toggle", "default": True, "description": "Allow browser setup tools to run."},
        {"key": "browser", "label": "2. BROWSER", "type": "choice", "options": ["edge", "chrome", "chromium"], "default": "edge", "description": "Uses a dedicated automation profile, never your normal profile."},
        {"key": "headless", "label": "3. SHOW BROWSER WINDOW", "type": "toggle", "default": False, "description": "ON lets you watch and interact with setup."},
        {"key": "profile_dir", "label": "4. AUTOMATION PROFILE FOLDER", "type": "text", "default": "", "placeholder": "Leave blank for Mark-LIII/config/browser_profile", "description": "Local dedicated browser profile."},
    ],
}

_LOCK = threading.RLock()
_ALLOWED_ORIGINS = {"elevenlabs.io", "aistudio.google.com", "console.groq.com", "platform.openai.com", "github.com"}
_ELEVENLABS_VOICE_ID = re.compile(r"\b[A-Za-z0-9]{20,32}\b")


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


def _guide_voice_setup() -> str:
    return (
        "JARVIS voice setup guide (English only): Step 1 — sign in to ElevenLabs in the dedicated browser. "
        "Step 2 — open API Keys and create an API key yourself; enter that secret directly into "
        "Plugin Settings → jarvis_voice → ELEVENLABS API KEY. Step 3 — open My Voices and choose a voice you are "
        "authorized to use. Step 4 — run list_elevenlabs_voice_ids; JARVIS can identify non-secret Voice IDs. "
        "Step 5 — select the intended Voice ID; JARVIS can write that non-secret ID to Plugin Settings → "
        "jarvis_voice → ELEVENLABS VOICE ID. Step 6 — use TEST VOICE. If anything fails, ask JARVIS for the error explanation."
    )


def _discover_elevenlabs_voice_ids() -> str:
    pw = context = None
    try:
        pw, context = _launch()
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://elevenlabs.io/app/voice-library", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        links = page.locator("a").evaluate_all("els => els.map(e => ({text:(e.innerText||'').trim(), href:e.href||''}))")
        found: dict[str, str] = {}
        for item in links:
            href = str(item.get("href", ""))
            text = str(item.get("text", "")).strip()
            for match in re.findall(r"(?:voice[_-]?id=|/voice/)([A-Za-z0-9]{20,32})", href, flags=re.I):
                found.setdefault(match, text or "Unknown voice")
        body = page.locator("body").inner_text(timeout=10000)
        for match in _ELEVENLABS_VOICE_ID.findall(body):
            if match not in found:
                found[match] = "Voice ID found in page"
        rows = [f"{name} — {voice_id}" for voice_id, name in found.items()]
        if not rows:
            return "No Voice IDs were exposed by the current ElevenLabs page. Open My Voices, select a voice, and ask JARVIS to inspect the page again."
        return "Discovered non-secret ElevenLabs Voice IDs:\n" + "\n".join(rows[:40])
    except Exception as exc:
        return f"Voice ID discovery stopped safely: {_redact(exc)}"
    finally:
        try:
            if context:
                context.close()
        finally:
            if pw:
                pw.stop()


def _set_voice_id(voice_id: str) -> str:
    value = str(voice_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9]{12,64}", value):
        return "That does not look like a valid ElevenLabs Voice ID."
    from memory.config_manager import save_plugin_config
    save_plugin_config("jarvis_voice", {"elevenlabs_voice_id": value})
    return "ElevenLabs Voice ID saved to jarvis_voice → ELEVENLABS VOICE ID."


def run(parameters: dict, player=None, session_memory=None) -> str:
    if not bool(_setting("enabled", True)):
        return "Browser Setup is disabled in Plugin Settings."
    action = str(parameters.get("action", "") or "").strip().lower()
    with _LOCK:
        try:
            if action == "guide_voice_setup":
                return _guide_voice_setup()
            if action == "list_elevenlabs_voice_ids":
                return _discover_elevenlabs_voice_ids()
            if action == "set_voice_id":
                return _set_voice_id(parameters.get("voice_id", ""))
            if action not in {"open", "inspect"}:
                return "Use browser_setup with action open, inspect, guide_voice_setup, list_elevenlabs_voice_ids, or set_voice_id."
            url = _safe_url(parameters.get("url", ""))
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
