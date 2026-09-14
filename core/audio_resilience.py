"""Small, output-only audio resilience helpers for JARVIS.

The Live API can deliver PCM in bursts. PortAudio's default output latency can
be too small for those bursts on some Windows audio devices, producing audible
micro-gaps even though the network/session is healthy.

This module only adjusts the native sounddevice RawOutputStream used for JARVIS
playback. Microphone/input streams and all Gemini/session behavior are untouched.
"""
from __future__ import annotations

import platform
from typing import Any

_PATCHED = False
_ORIGINAL_RAW_OUTPUT_STREAM = None


def install_output_latency_guard(sounddevice_module: Any) -> bool:
    """Patch RawOutputStream defaults once; return whether the patch is active.

    Only the 24 kHz mono PCM stream used by JARVIS is changed, and only when the
    caller has not already selected an explicit latency. Other sounddevice
    streams retain their existing behavior.
    """
    global _PATCHED, _ORIGINAL_RAW_OUTPUT_STREAM

    if _PATCHED:
        return True
    if platform.system() != "Windows":
        return False

    original = getattr(sounddevice_module, "RawOutputStream", None)
    if original is None or not callable(original):
        return False

    def resilient_raw_output_stream(*args, **kwargs):
        samplerate = kwargs.get("samplerate")
        if samplerate == 24000 and "latency" not in kwargs:
            # Give Windows/PortAudio enough output buffering to absorb small
            # delivery-time bursts from Gemini Live without changing the voice.
            kwargs["latency"] = "high"
        return original(*args, **kwargs)

    _ORIGINAL_RAW_OUTPUT_STREAM = original
    sounddevice_module.RawOutputStream = resilient_raw_output_stream
    _PATCHED = True
    return True
