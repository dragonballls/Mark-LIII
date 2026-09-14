"""Process and audio guards for the JARVIS checkout.

Python loads ``sitecustomize`` automatically during normal interpreter startup.
JARVIS acquires one named Windows mutex before UI/audio/network services start so
source and packaged launches cannot create multiple assistant instances. A
small output-only sounddevice guard gives the 24 kHz Live voice extra buffering.
"""

from __future__ import annotations

import os
import sys

_MUTEX_HANDLE = None
_MUTEX_NAME = r"Local\MarkLIII.JARVIS.Singleton"

_JARVIS_ENTRYPOINTS = {
    "main.py",
    "jarvis.exe",
    "mark-lii.exe",
    "mark-liii.exe",
}


def _guard_jarvis_process() -> None:
    global _MUTEX_HANDLE

    if os.name != "nt" or not sys.argv:
        return

    entry = os.path.basename(sys.argv[0]).lower()
    if entry not in _JARVIS_ENTRYPOINTS:
        return

    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_bool,
            ctypes.c_wchar_p,
        ]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.GetLastError.restype = ctypes.c_ulong

        _MUTEX_HANDLE = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        if not _MUTEX_HANDLE:
            raise RuntimeError("Windows could not create the JARVIS singleton mutex")

        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(_MUTEX_HANDLE)
            _MUTEX_HANDLE = None
            raise SystemExit(0)
    except SystemExit:
        raise
    except Exception as exc:
        # Fail closed: if singleton protection itself cannot be initialized,
        # do not risk starting a second JARVIS process.
        raise SystemExit(f"JARVIS singleton guard unavailable: {exc}")


def _install_audio_guard() -> None:
    """Install output buffering without touching microphone behavior."""
    try:
        import sounddevice as sd
        from core.audio_resilience import install_output_latency_guard
        install_output_latency_guard(sd)
    except Exception:
        # Audio resilience is deliberately non-fatal. A missing/changed
        # sounddevice installation must never prevent JARVIS from starting.
        pass


_guard_jarvis_process()
_install_audio_guard()
