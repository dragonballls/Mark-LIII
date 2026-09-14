"""Core package bootstrap for Mark 53.

The updater is started only for the real assistant entrypoint, not for tests or
one-off imports. It runs in a daemon thread and never blocks application startup.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _start_runtime_updater() -> None:
    if os.getenv("MARK_DISABLE_AUTO_UPDATE") == "1":
        return
    argv0 = Path(sys.argv[0]).name.lower() if sys.argv else ""
    runtime_entries = {"main.py", "mark-liii.exe", "jarvis.exe", "jarvis"}
    if argv0 not in runtime_entries:
        return
    try:
        from .self_updater import start_background_monitor
        start_background_monitor()
    except Exception:
        # Updating must never prevent the assistant from starting.
        return


_start_runtime_updater()
