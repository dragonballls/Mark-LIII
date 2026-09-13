"""Safe background updater for the Jarvis Mark-LIII fork.

The updater tracks FatihMakes/Mark-LIII ``main`` because the upstream project does
not publish GitHub Release objects. It never overwrites a dirty working tree,
creates a local recovery branch before applying an update, validates Python
syntax when a Python interpreter is available, and rolls the source tree back
when validation or dependency installation fails.

No UI changes, local LLMs, or computer-use agents are introduced here.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

UPSTREAM_URL = "https://github.com/FatihMakes/Mark-LIII.git"
UPSTREAM_REMOTE = "upstream"
UPSTREAM_BRANCH = "main"
DEFAULT_INTERVAL_SECONDS = 6 * 60 * 60
INITIAL_DELAY_SECONDS = 180
_LOCK = threading.Lock()
_STARTED = False


def _root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


ROOT = _root()
STATE_FILE = ROOT / ".jarvis_update_state.json"


def _log(message: str, logger: Callable[[str], None] | None = None) -> None:
    line = f"[Updater] {message}"
    try:
        (logger or print)(line)
    except Exception:
        pass


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=str(ROOT),
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def _git_result(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run("git", *args, check=check)


def _git(*args: str, check: bool = True) -> str:
    result = _git_result(*args, check=check)
    return (result.stdout or "").strip()


def _write_state(**values: str) -> None:
    try:
        import json

        current = {}
        if STATE_FILE.exists():
            try:
                current = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            except Exception:
                current = {}
        current.update(values)
        STATE_FILE.write_text(json.dumps(current, indent=2), encoding="utf-8")
    except Exception:
        pass


def _ensure_upstream(logger: Callable[[str], None] | None = None) -> bool:
    try:
        existing = _git("remote", "get-url", UPSTREAM_REMOTE, check=False)
        if existing:
            if existing.rstrip("/") != UPSTREAM_URL.rstrip("/"):
                _log(
                    f"remote '{UPSTREAM_REMOTE}' already points to {existing}; refusing to replace it.",
                    logger,
                )
                return False
            return True
        _git("remote", "add", UPSTREAM_REMOTE, UPSTREAM_URL)
        return True
    except Exception as exc:
        _log(f"cannot configure upstream remote: {exc}", logger)
        return False


def _working_tree_clean() -> bool:
    return _git("status", "--porcelain", check=True) == ""


def _current_sha() -> str:
    return _git("rev-parse", "HEAD")


def _upstream_sha() -> str:
    output = _git("ls-remote", UPSTREAM_URL, f"refs/heads/{UPSTREAM_BRANCH}")
    parts = output.split()
    if not parts:
        raise RuntimeError("upstream main returned no commit SHA")
    return parts[0]


def _changed_requirements(before: str) -> bool:
    diff = _git("diff", f"{before}..HEAD", "--", "requirements.txt", check=False)
    return bool(diff.strip())


def _python_for_validation() -> str | None:
    if not getattr(sys, "frozen", False):
        return sys.executable
    return shutil.which("python") or shutil.which("py")


def _validate_source() -> bool:
    python = _python_for_validation()
    if python is None:
        _log("source validation skipped: no external Python interpreter is available.")
        return True
    targets = ["main.py", "ui.py", "actions", "core", "memory", "plugins", "dashboard"]
    result = _run(python, "-m", "compileall", "-q", *targets, check=False)
    return result.returncode == 0


def _install_dependencies(logger: Callable[[str], None] | None = None) -> bool:
    python = _python_for_validation()
    if python is None:
        _log("dependency installation skipped: no external Python interpreter is available.", logger)
        return False
    result = _run(
        python,
        "-m",
        "pip",
        "install",
        "-r",
        "requirements.txt",
        "--disable-pip-version-check",
        "--no-input",
        check=False,
    )
    if result.returncode != 0:
        _log("pip dependency installation failed.", logger)
        return False
    return True


def _restart(logger: Callable[[str], None] | None = None) -> None:
    try:
        if getattr(sys, "frozen", False):
            command = [sys.executable, *sys.argv[1:]]
        else:
            command = [sys.executable, *sys.argv]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        subprocess.Popen(
            command,
            cwd=str(ROOT),
            close_fds=os.name != "nt",
            creationflags=flags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _log("restarting with the updated source.", logger)
        os._exit(0)
    except Exception as exc:
        _log(f"update installed but automatic restart failed: {exc}", logger)


def check_and_update(
    *,
    logger: Callable[[str], None] | None = None,
    restart: bool = True,
) -> dict[str, str | bool]:
    """Check upstream and safely merge a newer creator build.

    Returns a small status dictionary for the manual ``check_for_updates`` action.
    """
    with _LOCK:
        try:
            if not (ROOT / ".git").exists():
                message = "This installation is not a Git checkout; automatic source updates are disabled."
                _log(message, logger)
                return {"updated": False, "status": "unsupported", "message": message}

            if not _working_tree_clean():
                message = "Local changes are present, so the update was deferred to protect your work."
                _log(message, logger)
                return {"updated": False, "status": "deferred", "message": message}

            if not _ensure_upstream(logger):
                return {"updated": False, "status": "error", "message": "Upstream remote could not be configured safely."}

            local = _current_sha()
            remote = _upstream_sha()
            _write_state(last_check=datetime.now(timezone.utc).isoformat(), upstream_sha=remote)
            if local == remote:
                message = "Already current with FatihMakes/Mark-LIII main."
                _log(message, logger)
                return {"updated": False, "status": "current", "message": message, "local": local}

            _log(f"new creator build detected: {remote[:12]} (local {local[:12]}).", logger)
            _git("fetch", UPSTREAM_REMOTE, UPSTREAM_BRANCH, "--prune")
            fetched = _git("rev-parse", f"{UPSTREAM_REMOTE}/{UPSTREAM_BRANCH}")
            if fetched != remote:
                remote = fetched

            ancestry = _git_result("merge-base", "--is-ancestor", remote, "HEAD", check=False)
            if ancestry.returncode == 0:
                message = "The upstream build is already contained in this checkout."
                _log(message, logger)
                return {"updated": False, "status": "current", "message": message}

            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = f"jarvis-pre-update-{stamp}"
            _git("branch", backup, local)
            _log(f"recovery point created: {backup}.", logger)

            merge_result = _run("git", "merge", "--no-edit", "--no-ff", f"{UPSTREAM_REMOTE}/{UPSTREAM_BRANCH}", check=False)
            if merge_result.returncode != 0:
                _run("git", "merge", "--abort", check=False)
                message = "Upstream changes conflicted with local work, so nothing was applied."
                _log(message, logger)
                return {"updated": False, "status": "conflict", "message": message, "backup": backup}

            requirements_changed = _changed_requirements(local)
            if requirements_changed:
                _log("requirements.txt changed; synchronizing Python dependencies.", logger)
                if not _install_dependencies(logger):
                    _git("reset", "--hard", local, check=False)
                    message = "Dependency installation failed; the source update was rolled back."
                    _log(message, logger)
                    return {"updated": False, "status": "rolled_back", "message": message, "backup": backup}

            if not _validate_source():
                _git("reset", "--hard", local, check=False)
                message = "Source validation failed; the source update was rolled back."
                _log(message, logger)
                return {"updated": False, "status": "rolled_back", "message": message, "backup": backup}

            new_sha = _current_sha()
            _write_state(last_update=datetime.now(timezone.utc).isoformat(), previous_sha=local, current_sha=new_sha)
            message = f"Updated safely to creator build {new_sha[:12]}."
            _log(message, logger)
            result = {"updated": True, "status": "updated", "message": message, "backup": backup, "sha": new_sha}
            if restart:
                _restart(logger)
            return result
        except Exception as exc:
            message = f"Update check failed safely: {exc}"
            _log(message, logger)
            return {"updated": False, "status": "error", "message": message}


def _interval_seconds() -> int:
    raw = os.getenv("JARVIS_UPDATE_INTERVAL_HOURS", "6")
    try:
        return max(15 * 60, int(float(raw) * 3600))
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_SECONDS


def start_background_monitor(logger: Callable[[str], None] | None = None) -> None:
    """Start one daemon thread that checks the creator's branch periodically."""
    global _STARTED
    if _STARTED:
        return
    _STARTED = True

    def worker() -> None:
        time.sleep(INITIAL_DELAY_SECONDS)
        while True:
            check_and_update(logger=logger, restart=True)
            time.sleep(_interval_seconds())

    threading.Thread(target=worker, name="jarvis-updater", daemon=True).start()


if __name__ == "__main__":
    print(check_and_update(restart=False))
