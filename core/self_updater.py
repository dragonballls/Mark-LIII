"""Safe automatic updater for the Mark 53 / JARVIS checkout.

The updater follows the user's dragonballls/Mark-LIII main branch. It is deliberately
conservative: dirty worktrees and diverged local history are deferred; clean
fast-forward updates get a recovery branch, source validation, optional dependency
synchronization, and only then a restart handoff.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

REPOSITORY_URL = "https://github.com/dragonballls/Mark-LIII.git"
REMOTE = "origin"
BRANCH = "main"
DEFAULT_INTERVAL_SECONDS = 10 * 60
INITIAL_DELAY_SECONDS = 30
_LOCK = threading.Lock()
_STARTED = False


def _root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


ROOT = _root()
STATE_FILE = ROOT / ".mark_update_state.json"


def _log(message: str, logger: Callable[[str], None] | None = None) -> None:
    try:
        (logger or print)(f"[MarkUpdater] {message}")
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


def _git(*args: str, check: bool = True) -> str:
    result = _run("git", *args, check=check)
    return (result.stdout or "").strip()


def _write_state(**values: str) -> None:
    try:
        state = {}
        if STATE_FILE.exists():
            try:
                state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            except Exception:
                state = {}
        state.update(values)
        STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass


def _ensure_remote(logger: Callable[[str], None] | None = None) -> bool:
    try:
        existing = _git("remote", "get-url", REMOTE, check=False)
        if existing:
            return existing.rstrip("/") == REPOSITORY_URL.rstrip("/")
        _git("remote", "add", REMOTE, REPOSITORY_URL)
        return True
    except Exception as exc:
        _log(f"cannot configure GitHub remote: {exc}", logger)
        return False


def _clean_tree() -> bool:
    return _git("status", "--porcelain", check=True) == ""


def _head() -> str:
    return _git("rev-parse", "HEAD")


def _remote_head() -> str:
    output = _git("ls-remote", REPOSITORY_URL, f"refs/heads/{BRANCH}")
    parts = output.split()
    if not parts:
        raise RuntimeError("GitHub main returned no commit SHA")
    return parts[0]


def _python_for_validation() -> str | None:
    if not getattr(sys, "frozen", False):
        return sys.executable
    return shutil.which("python") or shutil.which("py")


def _validate_source(logger: Callable[[str], None] | None = None) -> bool:
    python = _python_for_validation()
    if python is None:
        _log("source validation skipped because no external Python interpreter is available.", logger)
        return True
    targets = [
        "main.py",
        "ui.py",
        "actions",
        "core",
        "memory",
        "plugins",
        "dashboard",
        "self_coding_engine",
    ]
    result = _run(python, "-m", "compileall", "-q", *targets, check=False)
    if result.returncode != 0:
        _log("Python source validation failed.", logger)
        if result.stderr:
            _log(result.stderr.strip(), logger)
        return False
    return True


def _requirements_changed(before: str) -> bool:
    return bool(_git("diff", f"{before}..HEAD", "--", "requirements.txt", check=False).strip())


def _install_dependencies(logger: Callable[[str], None] | None = None) -> bool:
    python = _python_for_validation()
    if python is None:
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
        _log("dependency installation failed.", logger)
        if result.stderr:
            _log(result.stderr.strip(), logger)
        return False
    return True


def _restart_after_update(logger: Callable[[str], None] | None = None) -> None:
    """Hand off restart to a detached Python helper so the singleton can release."""
    try:
        if getattr(sys, "frozen", False):
            command = [sys.executable, *sys.argv[1:]]
            helper_python = shutil.which("pythonw") or shutil.which("python") or shutil.which("pyw") or shutil.which("py")
        else:
            command = [sys.executable, *sys.argv]
            current = Path(sys.executable)
            helper_python = str(current.with_name("pythonw.exe")) if current.name.lower() == "python.exe" and current.with_name("pythonw.exe").exists() else sys.executable

        if helper_python:
            helper_code = (
                "import os,subprocess,sys,time; "
                "time.sleep(2); "
                "env=os.environ.copy(); env['JARVIS_RESTART_HANDOFF']='1'; "
                "subprocess.Popen(sys.argv[1:], cwd=os.getcwd(), env=env, "
                "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL);"
            )
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            subprocess.Popen(
                [helper_python, "-c", helper_code, *command],
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
                close_fds=os.name != "nt",
            )
            _log("update applied; restart handoff scheduled.", logger)
            os._exit(0)
        _log("update applied, but no restart interpreter was available.", logger)
    except Exception as exc:
        _log(f"automatic restart failed safely: {exc}", logger)


def check_and_update(
    *,
    logger: Callable[[str], None] | None = None,
    restart: bool = True,
) -> dict[str, str | bool]:
    """Check GitHub main and safely fast-forward this checkout when possible."""
    with _LOCK:
        try:
            if not (ROOT / ".git").exists():
                message = "This installation is not a Git checkout; automatic source updates are disabled."
                _log(message, logger)
                return {"updated": False, "status": "unsupported", "message": message}

            if not _clean_tree():
                message = "Local changes are present, so the update was deferred to protect your work."
                _log(message, logger)
                return {"updated": False, "status": "deferred", "message": message}

            if not _ensure_remote(logger):
                message = "The GitHub remote is not the Mark-LIII repository, so the update was refused."
                _log(message, logger)
                return {"updated": False, "status": "error", "message": message}

            local = _head()
            remote = _remote_head()
            _write_state(last_check=datetime.now(timezone.utc).isoformat(), remote_sha=remote)
            if local == remote:
                message = "Already current with dragonballls/Mark-LIII main."
                _log(message, logger)
                return {"updated": False, "status": "current", "message": message, "sha": local}

            _git("fetch", REMOTE, BRANCH, "--prune")
            fetched = _git("rev-parse", f"{REMOTE}/{BRANCH}")
            if fetched != remote:
                remote = fetched
                _write_state(remote_sha=remote)

            # The old Friday updater treated main as authoritative. Keep that useful
            # behavior, but only when local history is a strict ancestor, so divergent
            # or locally-ahead work is never overwritten automatically.
            local_is_ancestor = _run("git", "merge-base", "--is-ancestor", local, remote, check=False).returncode == 0
            remote_is_ancestor = _run("git", "merge-base", "--is-ancestor", remote, local, check=False).returncode == 0
            if not local_is_ancestor:
                status = "diverged" if not remote_is_ancestor else "ahead"
                message = "GitHub has changes that cannot be applied as a clean fast-forward; the update was deferred."
                _log(message, logger)
                return {"updated": False, "status": status, "message": message}

            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = f"mark-pre-update-{stamp}"
            _git("branch", backup, local)
            _log(f"recovery point created: {backup}.", logger)

            if _git("reset", "--hard", f"{REMOTE}/{BRANCH}", check=False) != "":
                # reset writes nothing to stdout in the normal case, so inspect HEAD below.
                pass

            if _head() != remote:
                _git("reset", "--hard", local, check=False)
                message = "The source checkout did not reach the fetched GitHub commit; the update was rolled back."
                _log(message, logger)
                return {"updated": False, "status": "rolled_back", "message": message, "backup": backup}

            if not _validate_source(logger):
                _git("reset", "--hard", local, check=False)
                message = "Source validation failed; the update was rolled back."
                _log(message, logger)
                return {"updated": False, "status": "rolled_back", "message": message, "backup": backup}

            if _requirements_changed(local) and not _install_dependencies(logger):
                _git("reset", "--hard", local, check=False)
                message = "Dependency installation failed; the source update was rolled back."
                _log(message, logger)
                return {"updated": False, "status": "rolled_back", "message": message, "backup": backup}

            if not _validate_source(logger):
                _git("reset", "--hard", local, check=False)
                message = "Post-install source validation failed; the update was rolled back."
                _log(message, logger)
                return {"updated": False, "status": "rolled_back", "message": message, "backup": backup}

            new_sha = _head()
            _write_state(last_update=datetime.now(timezone.utc).isoformat(), previous_sha=local, current_sha=new_sha)
            message = f"Updated safely to GitHub main {new_sha[:12]}."
            _log(message, logger)
            result = {"updated": True, "status": "updated", "message": message, "backup": backup, "sha": new_sha}
            if restart:
                _restart_after_update(logger)
            return result
        except Exception as exc:
            message = f"Update check failed safely: {exc}"
            _log(message, logger)
            return {"updated": False, "status": "error", "message": message}


def _interval_seconds() -> int:
    raw = os.getenv("MARK_UPDATE_INTERVAL_MINUTES", "10")
    try:
        return max(5 * 60, int(float(raw) * 60))
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_SECONDS


def start_background_monitor(logger: Callable[[str], None] | None = None) -> None:
    """Start exactly one background monitor for the running Mark process."""
    global _STARTED
    if _STARTED:
        return
    _STARTED = True

    def worker() -> None:
        time.sleep(INITIAL_DELAY_SECONDS)
        while True:
            check_and_update(logger=logger, restart=True)
            time.sleep(_interval_seconds())

    threading.Thread(target=worker, name="mark-auto-updater", daemon=True).start()


if __name__ == "__main__":
    print(check_and_update(restart=False))
