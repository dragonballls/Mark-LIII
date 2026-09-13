"""Optional JARVIS-style voice plugin.

This is intentionally self-contained: it does not import the live-session,
self-coding, updater, or other application internals. It provides an explicit
speech tool for callers that want a restrained British computer-assistant voice.

The plugin cannot replace Gemini Live's native response audio by itself; Mark 53
keeps ownership of its live session. This tool is for explicit on-demand speech,
notifications, or future host-level voice routing without coupling to the core.
"""
from __future__ import annotations

import asyncio
import io
import os
import re
import threading
from pathlib import Path

PLUGIN = {
    "name": "jarvis_voice",
    "description": (
        "Speaks text using a configurable JARVIS-inspired British computer-assistant voice. "
        "Use this tool when the user explicitly asks for the JARVIS voice, a spoken notification, "
        "or to hear a supplied sentence in the configured assistant voice. This plugin is separate "
        "from self_coding and does not modify the live-session engine."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "text": {
                "type": "STRING",
                "description": "The exact sentence to speak aloud.",
            },
        },
        "required": ["text"],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "jarvis_voice",
    "title": "JARVIS VOICE",
    "fields": [
        {
            "key": "enabled",
            "label": "Enable voice plugin",
            "type": "boolean",
            "description": "Allow the standalone JARVIS-style speech tool to run.",
            "default": True,
        },
        {
            "key": "engine",
            "label": "Voice engine",
            "type": "select",
            "options": ["edge", "elevenlabs"],
            "description": "Edge is free; ElevenLabs uses your own API key and selected voice ID.",
            "default": "edge",
        },
        {
            "key": "edge_voice",
            "label": "Edge voice",
            "type": "text",
            "description": "Recommended JARVIS-inspired British male voice: en-GB-RyanNeural.",
            "default": "en-GB-RyanNeural",
        },
        {
            "key": "edge_rate",
            "label": "Edge rate",
            "type": "text",
            "description": "Speech rate such as -8%, -5%, 0%, or +5%.",
            "default": "-5%",
        },
        {
            "key": "edge_pitch",
            "label": "Edge pitch",
            "type": "text",
            "description": "Pitch shift such as -10Hz, -5Hz, 0Hz, or +5Hz.",
            "default": "-8Hz",
        },
        {
            "key": "elevenlabs_api_key",
            "label": "ElevenLabs API key",
            "type": "password",
            "description": "Your own ElevenLabs key. Leave blank when using Edge.",
            "default": "",
        },
        {
            "key": "elevenlabs_voice_id",
            "label": "ElevenLabs voice ID",
            "type": "text",
            "description": "Use a voice you are licensed or authorized to use.",
            "default": "",
        },
        {
            "key": "elevenlabs_model",
            "label": "ElevenLabs model",
            "type": "text",
            "description": "Model ID sent to ElevenLabs.",
            "default": "eleven_multilingual_v2",
        },
        {
            "key": "volume",
            "label": "Volume",
            "type": "number",
            "description": "Playback multiplier from 0.1 to 2.0.",
            "default": 1.0,
        },
    ],
}

_LOCK = threading.Lock()


def _cfg():
    # Import only the generic plugin-settings store. No live-session, voice, or
    # self-coding internals are imported here.
    from memory.config_manager import get_plugin_config

    values = get_plugin_config("jarvis_voice")
    return {
        "enabled": bool(values.get("enabled", True)),
        "engine": str(values.get("engine", "edge") or "edge").strip().lower(),
        "edge_voice": str(values.get("edge_voice", "en-GB-RyanNeural") or "en-GB-RyanNeural").strip(),
        "edge_rate": str(values.get("edge_rate", "-5%") or "-5%").strip(),
        "edge_pitch": str(values.get("edge_pitch", "-8Hz") or "-8Hz").strip(),
        "elevenlabs_api_key": str(values.get("elevenlabs_api_key", "") or "").strip(),
        "elevenlabs_voice_id": str(values.get("elevenlabs_voice_id", "") or "").strip(),
        "elevenlabs_model": str(values.get("elevenlabs_model", "eleven_multilingual_v2") or "eleven_multilingual_v2").strip(),
        "volume": max(0.1, min(2.0, float(values.get("volume", 1.0)))),
    }


def _clean_text(text: str) -> str:
    text = re.sub(r"<ctrl\d+>", "", str(text), flags=re.IGNORECASE)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()


def _play_bytes(audio_bytes: bytes, volume: float) -> None:
    import miniaudio
    import numpy as np
    import sounddevice as sd

    decoded = miniaudio.decode(
        io.BytesIO(audio_bytes),
        output_format=miniaudio.SampleFormat.FLOAT32,
        nchannels=1,
    )
    samples = np.asarray(decoded.samples, dtype=np.float32) * volume
    samples = np.clip(samples, -1.0, 1.0)
    sd.play(samples, decoded.sample_rate)
    sd.wait()


async def _edge_audio(text: str, cfg: dict) -> bytes:
    import edge_tts

    communicate = edge_tts.Communicate(
        text,
        cfg["edge_voice"],
        rate=cfg["edge_rate"],
        pitch=cfg["edge_pitch"],
    )
    output = bytearray()
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio":
            output.extend(chunk.get("data", b""))
    return bytes(output)


def _elevenlabs_audio(text: str, cfg: dict) -> bytes:
    import requests

    api_key = cfg["elevenlabs_api_key"]
    voice_id = cfg["elevenlabs_voice_id"]
    if not api_key or not voice_id:
        raise RuntimeError("ElevenLabs is selected but its API key or voice ID is missing.")

    response = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
        json={
            "text": text,
            "model_id": cfg["elevenlabs_model"],
            "voice_settings": {"stability": 0.55, "similarity_boost": 0.80},
        },
        timeout=45,
    )
    response.raise_for_status()
    return response.content


def run(parameters: dict, player=None, session_memory=None) -> str:
    text = _clean_text(parameters.get("text", ""))
    if not text:
        return "Sir, there is nothing to speak."

    cfg = _cfg()
    if not cfg["enabled"]:
        return "The JARVIS voice plugin is disabled in Plugin Manager."

    # Keep playback serialized so two plugin calls cannot overlap and produce
    # garbled output.
    with _LOCK:
        try:
            if cfg["engine"] == "elevenlabs":
                audio = _elevenlabs_audio(text, cfg)
            else:
                audio = asyncio.run(_edge_audio(text, cfg))
            if not audio:
                return "Sir, the voice engine returned no audio."
            _play_bytes(audio, cfg["volume"])
            return "Spoken."
        except Exception as exc:
            msg = str(exc)
            if "No module named 'edge_tts'" in msg or "No module named 'miniaudio'" in msg:
                return "Sir, the JARVIS voice dependencies are not installed yet."
            return f"Sir, the JARVIS voice plugin failed: {msg}"
