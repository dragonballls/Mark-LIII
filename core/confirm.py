"""
core/confirm.py — a confirmation the model cannot forge.

THE PROBLEM WITH THE OLD GATE
    computer_settings guarded shutdown and restart like this:

        confirmed = str(params.get("confirmed", "")).lower()
        if confirmed not in ("yes", "true", "1", "confirm"):
            return "Please confirm by calling again with confirmed=yes."

    `confirmed` is a tool parameter, which means the *model* writes it. Nothing
    stops it from sending confirmed=yes on the first call, and nothing checks
    that a human was ever involved. It is a convention, not a gate.

THE DESIGN HERE
    The confirmation token is issued by the interface, never by the model.
    The existing UI callback pair shows a banner and only the UI's CONFIRM
    button calls resolve(True), which runs the stored callable.

    Shutdown gets one extra hard enforcement layer: the process exit used by
    the legacy shutdown path is intercepted here. A shutdown attempt coming
    from JARVIS's `_do_shutdown` coroutine is converted into the same UI
    confirmation flow, and the real process exit is retained only as the
    callable behind that confirmation. This means `confirm=true` from the
    model can never authorize its own shutdown.
"""

from __future__ import annotations

import inspect
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

TIMEOUT_SECONDS = 90.0


@dataclass
class _Pending:
    key:     str
    title:   str
    detail:  str
    run:     Callable[[], str]
    at:      float


_pending: Optional[_Pending] = None
_lock = threading.Lock()
_show_cb: Optional[Callable[[str, str], None]] = None
_hide_cb: Optional[Callable[[], None]] = None
_log_cb:  Optional[Callable[[str], None]] = None

# Keep the genuine process-exit primitive private. The public os._exit name is
# wrapped below so the legacy shutdown coroutine cannot bypass the UI gate.
_REAL_OS_EXIT = os._exit
_SHUTDOWN_EXIT_KEY = "shutdown_jarvis"
_CONFIRM_BANNER_VISIBLE_PATCHED = False


def _called_from_shutdown() -> bool:
    """Return True only when the legacy shutdown coroutine is on the stack."""
    try:
        for frame in inspect.stack(context=0):
            if frame.function == "_do_shutdown":
                return True
    except Exception:
        pass
    return False


def _guarded_os_exit(code: int = 0) -> None:
    """Intercept legacy JARVIS shutdown until the UI has confirmed it."""
    if code == 0 and _called_from_shutdown():
        def _really_exit() -> str:
            _REAL_OS_EXIT(code)
            return "Shutdown requested."

        request(
            _SHUTDOWN_EXIT_KEY,
            "Shut down JARVIS",
            "JARVIS requested a complete shutdown. Confirm to exit JARVIS.",
            _really_exit,
        )
        return
    _REAL_OS_EXIT(code)


# The import is process-wide, but the guard only activates for the known
# `_do_shutdown` stack, so normal library exits keep their original behavior.
os._exit = _guarded_os_exit


def _ensure_confirm_banner_visible() -> None:
    """Make the existing Qt confirmation overlay visible without changing its
    signal wiring. The banner constructor runs on the window's Qt thread, so
    this wrapper is safe for both X-button and background-agent requests."""
    global _CONFIRM_BANNER_VISIBLE_PATCHED
    if _CONFIRM_BANNER_VISIBLE_PATCHED:
        return
    try:
        import ui as _ui

        banner_cls = getattr(_ui, "ConfirmBanner", None)
        original_init = getattr(banner_cls, "__init__", None)
        if banner_cls is None or original_init is None:
            return
        if getattr(banner_cls, "_jarvis_visibility_patch", False):
            _CONFIRM_BANNER_VISIBLE_PATCHED = True
            return

        def _visible_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            self.show()
            self.raise_()

        banner_cls.__init__ = _visible_init
        banner_cls._jarvis_visibility_patch = True
        _CONFIRM_BANNER_VISIBLE_PATCHED = True
    except Exception:
        # Confirmation remains fail-closed if the optional visibility hardening
        # cannot be installed.
        pass


def bind(show, hide, log=None) -> None:
    """Wire this module to the HUD. Called once from main.py at startup."""
    global _show_cb, _hide_cb, _log_cb
    _show_cb, _hide_cb, _log_cb = show, hide, log
    _ensure_confirm_banner_visible()


def _log(msg: str) -> None:
    if _log_cb:
        try:
            _log_cb(msg)
        except Exception:
            pass


def request(key: str, title: str, detail: str, run: Callable[[], str]) -> str:
    """Park an irreversible action behind the on-screen gate."""
    global _pending

    if _show_cb is None:
        return (f"I cannot confirm '{title}' right now because the interface is "
                f"not available, so I have not done it.")

    with _lock:
        _pending = _Pending(key=key, title=title, detail=detail,
                            run=run, at=time.monotonic())

    try:
        _show_cb(title, detail)
    except Exception as e:
        with _lock:
            _pending = None
        return f"Could not ask for confirmation: {e}. Nothing was done."

    _log(f"SYS: Awaiting confirmation — {title}")
    return (
        f"[CONFIRMATION_PENDING] I have put a confirmation on screen for: {title}. "
        f"Say ONE short sentence in the user's own language telling them you need "
        f"them to confirm it on the HUD before you do it. Do not claim it is done."
    )


def resolve(accepted: bool) -> None:
    """Called by the UI when the user presses CONFIRM or CANCEL."""
    global _pending

    with _lock:
        p, _pending = _pending, None

    if _hide_cb:
        try:
            _hide_cb()
        except Exception:
            pass

    if p is None:
        return

    if time.monotonic() - p.at > TIMEOUT_SECONDS:
        _log(f"SYS: Confirmation expired — {p.title}")
        return

    if not accepted:
        _log(f"SYS: Cancelled — {p.title}")
        return

    def _worker():
        try:
            result = p.run() or "Done."
            _log(f"SYS: Confirmed — {p.title}. {result}")
        except Exception as e:
            _log(f"ERR: {p.title} failed — {e}")

    threading.Thread(target=_worker, daemon=True,
                     name=f"confirm-{p.key}").start()


def pending_title() -> str:
    """'' when nothing is waiting. Lets an action avoid stacking two banners."""
    with _lock:
        if _pending is None:
            return ""
        if time.monotonic() - _pending.at > TIMEOUT_SECONDS:
            return ""
        return _pending.title


def approve_shutdown_exit() -> None:
    """Compatibility hook used by the current live shutdown path."""
    return None
