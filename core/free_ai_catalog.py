"""Discover free/zero-priced hosted AI options.

This layer is intentionally non-invasive. It does not install local models, launch
computer-use agents, change the MARK LIII UI, or modify the assistant's existing
runtime path. It only reports hosted AI options that the assistant can evaluate.
"""
from __future__ import annotations

import json
import os
from typing import Any

import requests


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
    """Return a live, best-effort snapshot of hosted free AI options."""
    openrouter_models = _openrouter_free_models()
    configured = {
        "openrouter": bool(os.getenv("OPENROUTER_API_KEY")),
        "gemini": bool(os.getenv("GEMINI_API_KEY")),
    }

    return {
        "hosted_free": {
            "openrouter": {
                "provider": "OpenRouter",
                "model": "openrouter/free",
                "zero_priced": True,
                "configured": configured["openrouter"],
                "source": "https://openrouter.ai/openrouter/free",
                "models_found": len(openrouter_models),
                "models": openrouter_models[:40],
            },
            "gemini": {
                "provider": "Google Gemini API",
                "available_when_configured": configured["gemini"],
                "source": "https://ai.google.dev/gemini-api/docs/pricing",
            },
        },
        "disabled_by_design": {
            "local_llms": True,
            "computer_use_agents": True,
            "automatic_local_model_installation": True,
        },
        "notes": [
            "Free availability and quotas can change; re-check the live catalog before use.",
            "Free does not mean unlimited or guaranteed availability.",
            "This module only discovers hosted options; it does not install or launch agents.",
            "UI code is intentionally outside this layer.",
        ],
    }


def compact_text(snapshot: dict[str, Any]) -> str:
    """Format the discovery snapshot for the assistant conversation."""
    hosted = snapshot["hosted_free"]
    router = hosted["openrouter"]
    gemini = hosted["gemini"]
    return (
        "Hosted free AI discovery:\n"
        f"- OpenRouter free router: {'configured' if router['configured'] else 'not configured'}; "
        f"{router['models_found']} zero-priced model variants currently listed.\n"
        f"- Gemini free tier: {'configured' if gemini['available_when_configured'] else 'not configured'}.\n"
        "- Local LLMs: disabled.\n"
        "- Computer-use agents: disabled.\n"
        "- Automatic local AI installation: disabled."
    )


if __name__ == "__main__":
    print(json.dumps(discover(), indent=2))
