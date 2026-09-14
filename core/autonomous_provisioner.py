"""Autonomous provider provisioning for JARVIS.

The provisioner prefers already-configured credentials, then uses an existing
authenticated browser session to complete provider dashboard setup when the
provider exposes a normal key-creation flow. It never bypasses MFA/CAPTCHA,
never prints secrets, and never returns a key to the conversation.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Callable, Optional

import requests

from core.secret_store import get_secret, set_secret


@dataclass(frozen=True)
class Provider:
    name: str
    secret_name: str
    env_name: str
    setup_url: str
    key_pattern: re.Pattern[str]
    score: int
    validator: Callable[[str], bool]


def _validate_openrouter(key: str) -> bool:
    try:
        r = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=12,
        )
        return r.status_code == 200
    except Exception:
        return False


def _validate_groq(key: str) -> bool:
    try:
        r = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=12,
        )
        return r.status_code == 200
    except Exception:
        return False


def _validate_gemini(key: str) -> bool:
    try:
        r = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": key},
            timeout=12,
        )
        return r.status_code == 200
    except Exception:
        return False


PROVIDERS: tuple[Provider, ...] = (
    Provider(
        "OpenRouter", "llm/openrouter", "OPENROUTER_API_KEY",
        "https://openrouter.ai/settings/keys", re.compile(r"sk-or-v1-[A-Za-z0-9_-]{20,}"), 100,
        _validate_openrouter,
    ),
    Provider(
        "Groq", "llm/groq", "GROQ_API_KEY",
        "https://console.groq.com/keys", re.compile(r"gsk_[A-Za-z0-9_-]{20,}"), 95,
        _validate_groq,
    ),
    Provider(
        "Google Gemini", "llm/gemini", "GEMINI_API_KEY",
        "https://aistudio.google.com/app/apikey", re.compile(r"AIza[A-Za-z0-9_-]{20,}"), 90,
        _validate_gemini,
    ),
)

_LOCK = threading.RLock()


def _load_browser_context():
    """Open the existing dedicated browser profile and return Playwright objects."""
    from playwright.sync_api import sync_playwright
    from plugins.browser_setup import _profile_dir

    pw = sync_playwright().start()
    context = pw.chromium.launch_persistent_context(
        str(_profile_dir()),
        headless=False,
        viewport={"width": 1440, "height": 900},
    )
    return pw, context


def _capture_key(provider: Provider) -> Optional[str]:
    """Create/capture a provider key from an authorized dashboard session.

    Only the provider-specific key shape is captured. The value is written to
    the local secret store immediately and is never logged or returned.
    """
    pw = context = None
    try:
        pw, context = _load_browser_context()
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(provider.setup_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(1200)

        # Try common dashboard controls. A failed click is harmless; the page
        # may already contain an existing key or use a different label.
        for label in ("Create Key", "Create API Key", "Create new key", "New API Key"):
            try:
                button = page.get_by_text(label, exact=False).first
                if button.count() > 0:
                    button.click(timeout=5_000)
                    page.wait_for_timeout(600)
                    break
            except Exception:
                pass

        body = page.locator("body").inner_text(timeout=10_000)
        match = provider.key_pattern.search(body)
        if not match:
            # Some dashboards render the secret in inputs or DOM attributes.
            values = page.locator("input,textarea").evaluate_all("els => els.map(e => e.value || e.textContent || '')")
            for value in values:
                match = provider.key_pattern.search(str(value))
                if match:
                    break
        if not match:
            return None

        key = match.group(0)
        if not provider.validator(key):
            return None
        set_secret(provider.secret_name, key)
        return provider.secret_name
    except Exception:
        return None
    finally:
        try:
            if context:
                context.close()
        finally:
            if pw:
                pw.stop()


def _existing_provider() -> Optional[Provider]:
    ranked = sorted(PROVIDERS, key=lambda p: p.score, reverse=True)
    for provider in ranked:
        import os
        key = get_secret(provider.secret_name) or os.getenv(provider.env_name)
        if key and provider.validator(key):
            return provider
    return None


def provision_best(allow_browser: bool = True, logger: Callable[[str], None] | None = None) -> dict:
    """Provision the best currently supported free-first provider.

    Existing valid credentials are preferred. Missing credentials may be
    created through the user's already-authorized provider dashboard. If a
    provider cannot be provisioned, the next provider is tried.
    """
    log = logger or (lambda _msg: None)
    with _LOCK:
        ready = _existing_provider()
        if ready:
            log(f"Provisioner: {ready.name} credential already ready.")
            return {"status": "ready", "provider": ready.name, "secret_name": ready.secret_name}

        for provider in sorted(PROVIDERS, key=lambda p: p.score, reverse=True):
            if not allow_browser:
                break
            log(f"Provisioner: opening {provider.name} setup automatically.")
            if _capture_key(provider):
                log(f"Provisioner: {provider.name} credential acquired and stored securely.")
                return {"status": "ready", "provider": provider.name, "secret_name": provider.secret_name}

        return {
            "status": "needs_authorization",
            "provider": None,
            "secret_name": None,
            "message": "No provider credential could be provisioned. An authenticated provider session or required human verification is needed.",
        }


def provider_status() -> list[dict]:
    import os
    rows = []
    for provider in sorted(PROVIDERS, key=lambda p: p.score, reverse=True):
        secret_present = bool(get_secret(provider.secret_name) or os.getenv(provider.env_name))
        rows.append({
            "provider": provider.name,
            "free_first": True,
            "configured": secret_present,
            "score": provider.score,
        })
    return rows
