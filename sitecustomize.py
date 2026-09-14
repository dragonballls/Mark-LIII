"""Windows process guard for the JARVIS checkout.

Python loads ``sitecustomize`` automatically during normal interpreter startup.
When the repository's ``main.py`` is the launched program, this module acquires
one named Windows mutex before JARVIS imports UI/audio/network services.
A second launch exits immediately and therefore cannot create a second speaking
JARVIS instance.
"""

from __future__ import annotations

import os
import sys

_MUTEX_HANDLE = None
_MUTEX_NAME = r"Local\MarkLIII.JARVIS.Singleton"


def _guard_main_process() -> None:
    global _MUTEX_HANDLE

    if os.name != "nt":
        return
    if not sys.argv:
        return

    entry = os.path.basename(sys.argv[0]).lower()
    if entry != "main.py":
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


_guard_main_process()
