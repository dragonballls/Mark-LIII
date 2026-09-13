"""Discover zero-priced hosted models and open-source coding engines.

This module is deliberately additive: it does not alter the MARK LIII UI, replace
its native Gemini path, or install software automatically. It provides a small,
refreshable catalog the assistant can inspect before choosing a coding engine.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class AIEngine:
    name: str
    kind: str
    software_free: bool
    available: bool
    model: str = ""
    source: str = ""


OPEN_SOURCE_ENGINES = (
    ("OpenHands", "openhands", True),
    ("Goose", "goose", True),
    ("Aider", "aider", True),
    ("Gemini CLI", "gemini", True),
    ("GitHub Copilot CLI", "copilot", False),
)


def _command_available(command: str) -> bool:
    return shutil.which(command) is not None


def _openrouter_free_models() -> list[dict[str, Any]]:
    """Fetch currently published zero-priced OpenRouter model variants."""
    try:
        response = requests.get("https://openrouter.ai/api/v1/models", timeout=12)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []

    models: list[dict[str, Any]] = []
    for raw in payload.get("data", []):
        pricing = raw.get("pricing") or {}
        try:
            prompt = float(pricing.get("prompt", "-1"))
            completion = float(pricing.get("completion", "-1"))
        except (TypeError, ValueError):
            continue
        if prompt == 0.0 and completion == 0.0:
            models.append(
                {
                    "id": str(raw.get("id", "")),
                    "name": str(raw.get("name", raw.get("id", ""))),
                    "context_length": raw.get("context_length"),
                }
            )

    models.sort(key=lambda item: (-(item.get("context_length") or 0), item["id"]))
    return models


def discover() -> dict[str, Any]:
    """Return a live, best-effort snapshot of free AI options."""
    engines = [
        asdict(
            AIEngine(
                name=name,
                kind="coding_engine",
                software_free=software_free,
                available=_command_available(command),
                source="local_cli",
            )
        )
        for name, command, software_free in OPEN_SOURCE_ENGINES
    ]

    openrouter_models = _openrouter_free_models()
    configured = {
        "openrouter": bool(os.getenv("OPENROUTER_API_KEY")),
        "gemini": bool(os.getenv("GEMINI_API_KEY")),
    }

    return {
        "engines": engines,
        "hosted_free_router": {
            "provider": "OpenRouter",
            "model": "openrouter/free",
            "zero_priced": True,
            "configured": configured["openrouter"],
            "source": "https://openrouter.ai/openrouter/free",
            "models_found": len(openrouter_models),
            "models": openrouter_models[:40],
        },
        "gemini_free_tier": {
            "provider": "Google Gemini API",
            "available_when_configured": configured["gemini"],
            "source": "https://ai.google.dev/gemini-api/docs/pricing",
        },
        "notes": [
            "Free availability and quotas can change; re-check the live catalog before use.",
            "Free software does not necessarily mean free inference or unlimited usage.",
            "This discovery action never installs software automatically.",
            "UI code is intentionally outside this discovery layer.",
        ],
    }


def compact_text(snapshot: dict[str, Any]) -> str:
    """Format the discovery snapshot for the assistant conversation."""
    lines = ["Free AI discovery:"]
    for engine in snapshot["engines"]:
        status = "available" if engine["available"] else "not installed"
        license_note = "free software" if engine["software_free"] else "software may require a paid plan"
        lines.append(f"- {engine['name']}: {status}; {license_note}")

    router = snapshot["hosted_free_router"]
    lines.append(
        f"- OpenRouter free router: {'configured' if router['configured'] else 'not configured'}; "
        f"{router['models_found']} zero-priced model variants currently listed."
    )
    gemini = snapshot["gemini_free_tier"]
    lines.append(
        f"- Gemini free tier: {'configured' if gemini['available_when_configured'] else 'not configured'}."
    )
    return "\n".join(lines)


if __name__ == "__main__":
    print(json.dumps(discover(), indent=2))
