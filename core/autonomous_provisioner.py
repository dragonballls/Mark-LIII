"""Autonomous provider provisioning for JARVIS.

This module prefers existing local credentials, then uses an already-authorized
browser session to complete normal provider-dashboard key creation where the
provider exposes a usable flow. It never bypasses MFA/CAPTCHA or account access
controls, never logs credential values, and writes credentials to the local vault.
"""
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from typing import Callable, Optional

import requests

from core.secret_store import get_secret, set_secret


@dataclass(frozen=True)
class Provider:
    name: str
    capability: str
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


def _validate_elevenlabs(key: str) -> bool:
    try:
        r = requests.get(
            "https://api.elevenlabs.io/v1/user",
            headers={"xi-api-key": key},
            timeout=12,
        )
        return r.status_code == 200
    except Exception:
        return False


PROVIDERS: tuple[Provider, ...] = (
    Provider(
        "OpenRouter", "llm", "llm/openrouter", "OPENROUTER_API_KEY",
        "https://openrouter.ai/settings/keys",
        re.compile(r"sk-or-v1-[A-Za-z0-9_-]{20,}"), 100,
        _validate_openrouter,
    ),
    Provider(
        "Groq", "llm", "llm/groq", "GROQ_API_KEY",
        "https://console.groq.com/keys",
        re.compile(r"gsk_[A-Za-z0-9_-]{20,}"), 95,
        _validate_groq,
    ),
    Provider(
        "Google Gemini", "llm", "llm/gemini", "GEMINI_API_KEY",
        "https://aistudio.google.com/app/apikey",
        re.compile(r"AIza[A-Za-z0-9_-]{20,}"), 90,
        _validate_gemini,
    ),
    Provider(
        "ElevenLabs", "voice", "voice/elevenlabs", "ELEVENLABS_API_KEY",
        "https://elevenlabs.io/app/settings/api-keys",
        re.compile(r"sk_[A-Za-z0-9_-]{20,}"), 85,
        _validate_elevenlabs,
    ),
)

_LOCK = threading.RLock()


def _load_browser_context():
    """Use the existing dedicated browser setup profile."""
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
    """Capture a newly exposed credential from an authorized dashboard session."""
    pw = context = None
    try:
        pw, context = _load_browser_context()
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(provider.setup_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(1500)

        for label in (
            "Create Key", "Create API Key", "Create new key", "New API Key",
            "Create an API key", "Create API key",
        ):
            try:
                loc = page.get_by_text(label, exact=False).first
                if loc.count() > 0:
                    loc.click(timeout=5_000)
                    page.wait_for_timeout(800)
                    break
            except Exception:
                pass

        values = []
        try:
            values.extend(page.locator("input,textarea").evaluate_all(
                "els => els.map(e => e.value || e.textContent || '')"
            ))
        except Exception:
            pass
        try:
            values.append(page.locator("body").inner_text(timeout=10_000))
        except Exception:
            pass

        for raw in values:
            match = provider.key_pattern.search(str(raw))
            if not match:
                continue
            key = match.group(0)
            if not provider.validator(key):
                continue
            set_secret(provider.secret_name, key)
            # Make the new credential immediately available to the running
            # process and to child processes without printing its value.
            os.environ[provider.env_name] = key
            return provider.secret_name
        return None
    except Exception:
        return None
    finally:
        try:
            if context:
                context.close()
        finally:
            if pw:
                pw.stop()


def _provider_ready(provider: Provider) -> bool:
    key = get_secret(provider.secret_name) or os.getenv(provider.env_name)
    return bool(key and provider.validator(key))


def _existing_provider(capability: str | None = None) -> Optional[Provider]:
    ranked = sorted(PROVIDERS, key=lambda p: p.score, reverse=True)
    for provider in ranked:
        if capability and provider.capability != capability:
            continue
        if _provider_ready(provider):
            return provider
    return None


def provision_best(
    allow_browser: bool = True,
    capability: str = "llm",
    logger: Callable[[str], None] | None = None,
) -> dict:
    """Provision the highest-scored ready provider for a capability."""
    log = logger or (lambda _msg: None)
    with _LOCK:
        ready = _existing_provider(capability)
        if ready:
            log(f"Provisioner: {ready.name} is already ready.")
            return {"status": "ready", "provider": ready.name, "secret_name": ready.secret_name}
        if not allow_browser:
            return {
                "status": "needs_authorization",
                "provider": None,
                "secret_name": None,
                "message": f"No {capability} provider credential is currently configured.",
            }
        for provider in sorted(PROVIDERS, key=lambda p: p.score, reverse=True):
            if provider.capability != capability:
                continue
            log(f"Provisioner: opening {provider.name} setup automatically.")
            if _capture_key(provider):
                log(f"Provisioner: {provider.name} credential acquired and stored securely.")
                return {"status": "ready", "provider": provider.name, "secret_name": provider.secret_name}
        return {
            "status": "needs_authorization",
            "provider": None,
            "secret_name": None,
            "message": f"No {capability} provider credential could be provisioned. Required account authorization may still be needed.",
        }


def provision_all(allow_browser: bool = True, logger: Callable[[str], None] | None = None) -> dict:
    """Provision one working LLM provider and one working voice provider."""
    results = {}
    for capability in ("llm", "voice"):
        results[capability] = provision_best(
            allow_browser=allow_browser,
            capability=capability,
            logger=logger,
        )
    ready = [result["provider"] for result in results.values() if result.get("status") == "ready"]
    return {
        "status": "ready" if ready else "needs_authorization",
        "ready": ready,
        "results": results,
        "message": "Provisioning completed for: " + ", ".join(ready) if ready else "No supported provider credential is ready yet.",
    }


def provider_status() -> list[dict]:
    rows = []
    for provider in sorted(PROVIDERS, key=lambda p: p.score, reverse=True):
        rows.append({
            "provider": provider.name,
            "capability": provider.capability,
            "free_first": True,
            "configured": _provider_ready(provider),
            "score": provider.score,
        })
    return rows
