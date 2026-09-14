"""Autonomous provisioning for JARVIS voice and non-LLM services.

This module deliberately does not provision, search for, rotate, or configure
LLM/API providers. JARVIS keeps using its existing cloud model connection.
It may provision the standalone voice plugin through an already-authorized
provider dashboard, then store the credential in the local secret vault.
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
    secret_name: str
    env_name: str
    setup_url: str
    key_pattern: re.Pattern[str]
    score: int
    validator: Callable[[str], bool]


def _validate_elevenlabs(key: str) -> bool:
    try:
        response = requests.get(
            "https://api.elevenlabs.io/v1/user",
            headers={"xi-api-key": key},
            timeout=12,
        )
        return response.status_code == 200
    except Exception:
        return False


PROVIDERS: tuple[Provider, ...] = (
    Provider(
        "ElevenLabs",
        "voice/elevenlabs",
        "ELEVENLABS_API_KEY",
        "https://elevenlabs.io/app/settings/api-keys",
        re.compile(r"sk_[A-Za-z0-9_-]{20,}"),
        100,
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


def _configure_voice_provider(key: str, logger: Callable[[str], None] | None = None) -> None:
    """Select a usable authorized voice and write only its non-secret ID."""
    try:
        response = requests.get(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": key},
            timeout=15,
        )
        response.raise_for_status()
        voices = response.json().get("voices") or []
        candidates = [voice for voice in voices if isinstance(voice, dict) and voice.get("voice_id")]
        if not candidates:
            return
        chosen = sorted(
            candidates,
            key=lambda voice: (
                0 if any(term in str(voice.get("name", "")).lower() for term in ("assistant", "british", "uk", "jarvis")) else 1,
                str(voice.get("name", "")).lower(),
            ),
        )[0]
        from memory.config_manager import save_plugin_config
        save_plugin_config(
            "jarvis_voice",
            {
                "engine": "elevenlabs",
                "elevenlabs_voice_id": str(chosen["voice_id"]),
            },
        )
        if logger:
            logger(f"Provisioner: selected accessible ElevenLabs voice '{chosen.get('name', 'voice')}'.")
    except Exception:
        return


def _capture_key(provider: Provider) -> Optional[str]:
    """Create/capture a provider key through an already-authorized dashboard."""
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
                locator = page.get_by_text(label, exact=False).first
                if locator.count() > 0:
                    locator.click(timeout=5_000)
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
            os.environ[provider.env_name] = key
            _configure_voice_provider(key)
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


def provision_best(allow_browser: bool = True, logger: Callable[[str], None] | None = None) -> dict:
    """Provision the standalone voice service only."""
    log = logger or (lambda _msg: None)
    with _LOCK:
        provider = PROVIDERS[0]
        if _provider_ready(provider):
            key = get_secret(provider.secret_name) or os.getenv(provider.env_name)
            _configure_voice_provider(key, log)
            log("Provisioner: ElevenLabs voice is already ready.")
            return {"status": "ready", "provider": provider.name, "secret_name": provider.secret_name}
        if not allow_browser:
            return {
                "status": "needs_authorization",
                "provider": None,
                "secret_name": None,
                "message": "No voice credential is currently configured.",
            }
        log("Provisioner: opening ElevenLabs voice setup automatically.")
        if _capture_key(provider):
            log("Provisioner: ElevenLabs voice credential acquired and stored securely.")
            return {"status": "ready", "provider": provider.name, "secret_name": provider.secret_name}
        return {
            "status": "needs_authorization",
            "provider": None,
            "secret_name": None,
            "message": "ElevenLabs could not be provisioned automatically; provider authorization may still be required.",
        }


def provision_all(allow_browser: bool = True, logger: Callable[[str], None] | None = None) -> dict:
    """Provision supported non-LLM services; currently the standalone voice service."""
    result = provision_best(allow_browser=allow_browser, logger=logger)
    ready = [result["provider"]] if result.get("status") == "ready" else []
    return {
        "status": "ready" if ready else "needs_authorization",
        "ready": ready,
        "results": {"voice": result},
        "message": "Provisioning completed for: " + ", ".join(ready) if ready else result.get("message", "No supported non-LLM service is ready."),
    }


def provider_status() -> list[dict]:
    provider = PROVIDERS[0]
    return [{
        "provider": provider.name,
        "capability": "voice",
        "free_first": True,
        "configured": _provider_ready(provider),
        "score": provider.score,
    }]
