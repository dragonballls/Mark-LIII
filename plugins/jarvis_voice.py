"""Optional JARVIS-style voice plugin.

Standalone speech plugin. It stays separate from the live-session engine and the
self-coding engine. Plugin Manager controls whether it is available.

The live Gemini session is the sole runtime speaker. This plugin remains available
for configuration and explicit voice testing, but its model-callable ``run`` path
never plays audio, preventing a second voice from speaking over the Live session.
"""
from __future__ import annotations

import asyncio
import io
import os
import re
import threading

PLUGIN = {
    "name": "jarvis_voice",
    "description": (
        "Standalone JARVIS-inspired British speech configuration and explicit voice testing. "
        "The live Gemini session is the sole runtime speaker, so this plugin never creates a "
        "second voice during ordinary conversation. The autonomous provisioner may configure "
        "authorized ElevenLabs credentials without exposing secrets."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {"text": {"type": "STRING", "description": "Text for an explicit voice test."}},
        "required": ["text"],
    },
}


def _auto_configure(values: dict):
    try:
        from memory.config_manager import save_plugin_config
        engine = str(values.get("engine") or "edge").strip().lower()
        if engine not in {"edge", "elevenlabs"}:
            engine = "edge"
        save_plugin_config(
            "jarvis_voice",
            {
                "enabled": True,
                "engine": engine,
                "edge_voice": str(values.get("edge_voice") or "en-GB-RyanNeural").strip(),
                "edge_rate": str(values.get("edge_rate") or "-5%").strip(),
                "edge_pitch": str(values.get("edge_pitch") or "-8Hz").strip(),
                "elevenlabs_voice_id": str(values.get("elevenlabs_voice_id") or "").strip(),
                "elevenlabs_model": str(values.get("elevenlabs_model") or "eleven_multilingual_v2").strip(),
                "volume": str(values.get("volume") or "1.0").strip(),
            },
        )

        from core.autonomous_provisioner import provision_best
        result = provision_best(allow_browser=True)
        if result.get("status") == "ready":
            return True, "Voice settings configured automatically and the authorized voice service is ready."
        return True, "Voice defaults configured automatically. Authorized ElevenLabs provisioning was not completed; the free Edge voice remains available."
    except Exception as exc:
        return False, f"Voice auto-configuration failed safely: {exc}"


PLUGIN_SETTINGS = {
    "namespace": "jarvis_voice",
    "title": "JARVIS VOICE — EASY AUTOMATIC SETUP",
    "fields": [
        {"key": "enabled", "label": "1. VOICE PLUGIN ENABLED", "type": "toggle", "default": True, "description": "Leave ON to allow this standalone voice tool."},
        {"key": "engine", "label": "2. VOICE ENGINE", "type": "choice", "options": ["edge", "elevenlabs"], "default": "edge", "description": "EDGE is free. ELEVENLABS uses an authorized account credential stored in the local vault."},
        {"key": "edge_voice", "label": "3. FREE EDGE VOICE", "type": "text", "default": "en-GB-RyanNeural", "placeholder": "en-GB-RyanNeural", "description": "Recommended British male computer-assistant voice."},
        {"key": "edge_rate", "label": "4. EDGE SPEED", "type": "text", "default": "-5%", "placeholder": "-5%", "description": "Slightly measured delivery."},
        {"key": "edge_pitch", "label": "5. EDGE PITCH", "type": "text", "default": "-8Hz", "placeholder": "-8Hz", "description": "Deeper profile."},
        {"key": "elevenlabs_api_key", "label": "6. ELEVENLABS API KEY — MANAGED AUTOMATICALLY", "type": "password", "default": "", "placeholder": "Managed by secure local vault", "description": "Do not paste the key into chat. Automatic provisioning stores it in the local vault."},
        {"key": "elevenlabs_voice_id", "label": "7. ELEVENLABS VOICE ID", "type": "text", "default": "", "placeholder": "Auto-filled when an authorized voice is discovered", "description": "Non-secret voice identifier."},
        {"key": "elevenlabs_model", "label": "8. ELEVENLABS MODEL", "type": "text", "default": "eleven_multilingual_v2", "description": "Normally leave this unchanged."},
        {"key": "volume", "label": "9. VOLUME", "type": "text", "default": "1.0", "placeholder": "1.0", "description": "1.0 = normal volume."},
    ],
}

_LOCK = threading.Lock()


def _vault_key() -> str:
    try:
        from core.secret_store import get_secret
        return get_secret("voice/elevenlabs") or ""
    except Exception:
        return ""


def _cfg_from(values: dict | None = None) -> dict:
    if values is None:
        from memory.config_manager import get_plugin_config
        values = get_plugin_config("jarvis_voice")
    try:
        volume = float(values.get("volume", 1.0))
    except (TypeError, ValueError):
        volume = 1.0
    return {
        "enabled": bool(values.get("enabled", True)),
        "engine": str(values.get("engine", "edge") or "edge").strip().lower(),
        "edge_voice": str(values.get("edge_voice", "en-GB-RyanNeural") or "en-GB-RyanNeural").strip(),
        "edge_rate": str(values.get("edge_rate", "-5%") or "-5%").strip(),
        "edge_pitch": str(values.get("edge_pitch", "-8Hz") or "-8Hz").strip(),
        "elevenlabs_api_key": _vault_key() or str(values.get("elevenlabs_api_key", "") or "").strip() or os.getenv("ELEVENLABS_API_KEY", ""),
        "elevenlabs_voice_id": str(values.get("elevenlabs_voice_id", "") or "").strip(),
        "elevenlabs_model": str(values.get("elevenlabs_model", "eleven_multilingual_v2") or "eleven_multilingual_v2").strip(),
        "volume": max(0.1, min(2.0, volume)),
    }


def _clean_text(text: str) -> str:
    text = re.sub(r"<ctrl\d+>", "", str(text), flags=re.IGNORECASE)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()


def _play_bytes(audio_bytes: bytes, volume: float) -> None:
    import miniaudio
    import numpy as np
    import sounddevice as sd
    decoded = miniaudio.decode(io.BytesIO(audio_bytes), output_format=miniaudio.SampleFormat.FLOAT32, nchannels=1)
    samples = np.asarray(decoded.samples, dtype=np.float32) * volume
    sd.play(np.clip(samples, -1.0, 1.0), decoded.sample_rate)
    sd.wait()


async def _edge_audio(text: str, cfg: dict) -> bytes:
    import edge_tts
    output = bytearray()
    communicate = edge_tts.Communicate(text, cfg["edge_voice"], rate=cfg["edge_rate"], pitch=cfg["edge_pitch"])
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio":
            output.extend(chunk.get("data", b""))
    return bytes(output)


def _elevenlabs_audio(text: str, cfg: dict) -> bytes:
    import requests
    if not cfg["elevenlabs_api_key"] or not cfg["elevenlabs_voice_id"]:
        raise RuntimeError("ElevenLabs requires an authorized credential and Voice ID.")
    response = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{cfg['elevenlabs_voice_id']}",
        headers={"xi-api-key": cfg["elevenlabs_api_key"], "Content-Type": "application/json"},
        json={"text": text, "model_id": cfg["elevenlabs_model"], "voice_settings": {"stability": 0.55, "similarity_boost": 0.80}},
        timeout=45,
    )
    response.raise_for_status()
    return response.content


def _speak(text: str, cfg: dict) -> str:
    audio = _elevenlabs_audio(text, cfg) if cfg["engine"] == "elevenlabs" else asyncio.run(_edge_audio(text, cfg))
    if not audio:
        raise RuntimeError("The voice service returned no audio.")
    _play_bytes(audio, cfg["volume"])
    return "Voice test successful."


def _test_voice(values: dict):
    try:
        cfg = _cfg_from(values if values else None)
        if not cfg["enabled"]:
            return False, "Turn VOICE PLUGIN ENABLED ON first."
        return True, _speak("Good evening, sir. Your JARVIS voice configuration is working.", cfg)
    except Exception as exc:
        msg = str(exc)
        if "No module named 'edge_tts'" in msg or "No module named 'miniaudio'" in msg:
            return False, "Voice dependencies are not installed yet."
        return False, f"Voice test failed: {msg}"


def _auto_configure_and_test(values: dict):
    ok, message = _auto_configure(values)
    if not ok:
        return ok, message
    tested, test_message = _test_voice({})
    if tested:
        return True, f"{message} Test successful."
    return True, f"{message} Configuration is saved; voice test was not completed: {test_message}"


PLUGIN_SETTINGS["action"] = {"label": "▸ AUTO-CONFIGURE + TEST VOICE", "run": _auto_configure_and_test}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Compatibility tool endpoint: never play audio during normal live chat.

    The native Gemini Live session already owns the runtime audio output. Having
    this callable tool also synthesize speech would create a second speaker.
    Explicit voice playback remains available only through Plugin Manager's
    dedicated test action.
    """
    text = _clean_text(parameters.get("text", ""))
    if not text:
        return "The voice plugin is configured for explicit testing only."
    cfg = _cfg_from()
    if not cfg["enabled"]:
        return "The JARVIS voice plugin is disabled in Plugin Manager."
    return "Voice playback is reserved for the explicit Plugin Manager voice test; the live JARVIS session is the sole runtime speaker."
