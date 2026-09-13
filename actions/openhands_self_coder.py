"""OpenHands-backed autonomous coding action for MARK LIII (53).

This action is intentionally isolated from the existing dev_agent action. It lets
MARK LIII use OpenHands for repository-level software work without making
OpenHands a hard dependency of the rest of the assistant at import time.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from integrations.openhands_agent import OpenHandsUnavailable, run as run_openhands


def _base_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _workspace_from(value: str | None) -> Path:
    raw = (value or "").strip()
    path = (_base_dir() if not raw else Path(raw)).expanduser().resolve()
    return path


def _git_status(workspace: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(workspace), "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if result.returncode != 0:
            return "not-a-git-repo"
        return result.stdout.strip()
    except Exception:
        return "git-unavailable"


def _git_root(workspace: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if result.returncode != 0:
            return None
        return Path(result.stdout.strip()).resolve()
    except Exception:
        return None


def self_code(parameters: dict, player=None, speak=None, **_: Any) -> str:
    p = parameters or {}
    goal = str(p.get("goal", "")).strip()
    workspace = _workspace_from(p.get("workspace"))
    max_iterations = max(1, min(int(p.get("max_iterations", 30)), 100))
    require_clean = bool(p.get("require_clean", True))

    if not goal:
        return "Tell me what software change you want me to make, sir."
    if not workspace.is_dir():
        return f"Workspace does not exist: {workspace}"

    root = _git_root(workspace)
    if root is None:
        return f"Workspace is not a Git repository: {workspace}"

    status = _git_status(root)
    if require_clean and status:
        return (
            "I stopped before changing the repository because it has uncommitted "
            "changes. Commit or stash those changes first."
        )

    full_goal = (
        "Work only inside this repository. Implement the requested software change "
        "carefully and preserve existing behavior. The graphical/user interface is "
        "FROZEN for this development phase: do not edit UI layouts, themes, HUDs, "
        "widgets, styling, animations, windows, or other presentation code unless "
        "the request explicitly asks for a UI change. Run relevant tests or validation "
        "commands before finishing. Do not modify credentials, secrets, or unrelated "
        "system settings. Leave the repository in a reviewable state.\n\n"
        f"REQUEST:\n{goal}"
    )

    if player:
        try:
            player.write_log(f"[OpenHands] workspace={root}")
            player.write_log(f"[OpenHands] goal={goal}")
        except Exception:
            pass
    if speak:
        try:
            speak("OpenHands is taking the coding task, sir.")
        except Exception:
            pass

    try:
        events = run_openhands(root, full_goal, max_iterations=max_iterations)
    except OpenHandsUnavailable as exc:
        return f"OpenHands is unavailable: {exc}"
    except Exception as exc:
        return f"OpenHands coding run failed safely: {exc}"

    completed_status = _git_status(root)
    message = (
        f"OpenHands finished the coding run in {root}. "
        f"Repository changes detected: {'yes' if completed_status else 'no'}."
    )
    if events:
        message += f" Events: {len(events)}."
    if player:
        try:
            player.write_log(f"[OpenHands] {message}")
        except Exception:
            pass
    if speak:
        try:
            speak("The coding run is complete, sir.")
        except Exception:
            pass
    return message


TOOL = {
    "name": "openhands_self_coder",
    "description": (
        "Uses OpenHands as the preferred repository-level coding engine. "
        "It edits an explicit Git workspace, runs bounded iterations, preserves "
        "existing behavior, and freezes the UI unless a UI change is explicitly requested."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "goal": {
                "type": "STRING",
                "description": "The software change, repair, refactor, or improvement to implement."
            },
            "workspace": {
                "type": "STRING",
                "description": "Absolute repository path. Defaults to the MARK LIII repository."
            },
            "max_iterations": {
                "type": "INTEGER",
                "description": "Maximum OpenHands iterations, capped at 100."
            },
            "require_clean": {
                "type": "BOOLEAN",
                "description": "Stop before editing when the Git worktree is dirty (default true)."
            }
        },
        "required": ["goal"]
    },
    "handler": self_code,
}
