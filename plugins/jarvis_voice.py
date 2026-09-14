"""Optional JARVIS-style voice plugin.

Standalone speech plugin. It stays separate from the live-session engine and the
self-coding engine. Plugin Manager controls whether it is available.
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
        "Standalone JARVIS-inspired British speech. Turn this plugin ON in Plugin Manager, "
        "then open Plugin Settings. Choose FREE EDGE or ELEVENLABS and use TEST VOICE. "
        "This plugin never touches the self-coding engine or Mark 53 session engine."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {"text": {"type": "STRING", "description": "Sentence to speak aloud."}},
        "required": ["text"],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "jarvis_voice",
    "title": "JARVIS VOICE — EASY SETUP",
    "fields": [
        {"key": "enabled", "label": "1. VOICE PLUGIN ENABLED", "type": "toggle", "default": True, "description": "Leave ON to allow this standalone voice tool."},
        {"key": "engine", "label": "2. VOICE ENGINE — FREE EDGE / ELEVENLABS", "type": "choice", "options": ["edge", "elevenlabs"], "default": "edge", "description": "EDGE = free. ELEVENLABS = authorized account credential."},
        {"key": "edge_voice", "label": "3. FREE EDGE VOICE", "type": "text", "default": "en-GB-RyanNeural", "placeholder": "en-GB-RyanNeural", "description": "Recommended British male computer-assistant voice."},
        {"key": "edge_rate", "label": "4. EDGE SPEED", "type": "text", "default": "-5%", "placeholder": "-5%", "description": "Leave at -5% for a slightly measured delivery."},
        {"key": "edge_pitch", "label": "5. EDGE PITCH", "type": "text", "default": "-8Hz", "placeholder": "-8Hz", "description": "Leave at -8Hz for a deeper profile."},
        {"key": "elevenlabs_api_key", "label": "6. ELEVENLABS API KEY", "type": "password", "default": "", "placeholder": "Only needed for ElevenLabs", "description": "The plugin prefers the protected local credential vault when available."},
        {"key": "elevenlabs_voice_id", "label": "7. ELEVENLABS VOICE ID", "type": "text", "default": "", "placeholder": "Authorized Voice ID", "description": "Non-secret voice identifier."},
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
        cfg = _cfg_from(values)
        if not cfg["enabled"]:
            return False, "Turn VOICE PLUGIN ENABLED ON first."
        return True, _speak("Good evening, sir. Your JARVIS voice configuration is working.", cfg)
    except Exception as exc:
        msg = str(exc)
        if "No module named 'edge_tts'" in msg or "No module named 'miniaudio'" in msg:
            return False, "Voice dependencies are not installed yet."
        return False, f"Voice test failed: {msg}"


PLUGIN_SETTINGS["action"] = {"label": "▸ TEST VOICE", "run": _test_voice}


def run(parameters: dict, player=None, session_memory=None) -> str:
    text = _clean_text(parameters.get("text", ""))
    if not text:
        return "Sir, there is nothing to speak."
    cfg = _cfg_from()
    if not cfg["enabled"]:
        return "The JARVIS voice plugin is disabled in Plugin Manager."
    with _LOCK:
        try:
            return _speak(text, cfg)
        except Exception as exc:
            msg = str(exc)
            if "No module named 'edge_tts'" in msg or "No module named 'miniaudio'" in msg:
                return "Sir, the JARVIS voice dependencies are not installed yet."
            return f"Sir, the JARVIS voice plugin failed: {msg}"
