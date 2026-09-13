"""Self-coding plugin backed by the detached, host-independent coding engine.

User-facing plugin wrapper for the standalone self-coding runtime. The engine and
coding workflow remain isolated from Mark 53's live-session voice system.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from google import genai
from google.genai import types

from memory.config_manager import get_gemini_key, get_plugin_setting
from self_coding_engine import CodingPlan, CodingStep, SelfCodingEngine

PLUGIN = {
    "name": "self_coding",
    "description": (
        "Safely implement, repair, and test code in the configured workspace. "
        "Turn this plugin ON in Plugin Manager, configure the workspace, then ask Mark "
        "to implement or fix code. It never modifies its own plugin, engine, secrets, or build output."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {"goal": {"type": "STRING", "description": "The concrete coding objective to implement."}},
        "required": ["goal"],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "self_coding",
    "title": "SELF-CODING ENGINE — EASY SETUP",
    "fields": [
        {"key": "workspace", "label": "1. WORKSPACE", "type": "text", "description": "Folder Mark is allowed to edit. Blank = this Mark 53 installation.", "default": "", "placeholder": "C:\\Projects\\MyApp"},
        {"key": "model", "label": "2. CODING MODEL", "type": "text", "description": "Gemini model used to plan, write, repair, and review code.", "default": "gemini-3.8-flash", "placeholder": "gemini-3.8-flash"},
        {"key": "max_attempts", "label": "3. REPAIR ATTEMPTS", "type": "text", "description": "Maximum attempts for each coding step. Recommended: 3.", "default": "3", "placeholder": "3"},
        {"key": "run_tests", "label": "4. RUN TESTS AUTOMATICALLY", "type": "toggle", "description": "ON = Mark verifies syntax and runs the configured test command after changes.", "default": True},
        {"key": "test_command", "label": "5. TEST COMMAND (OPTIONAL)", "type": "text", "description": "Leave blank to auto-detect pytest/compileall. Example: python -m pytest -q", "default": "", "placeholder": "Leave blank for automatic testing"},
        {"key": "auto_commit", "label": "6. AUTO-COMMIT SUCCESSFUL CHANGES", "type": "toggle", "description": "OFF is safest. ON creates a local Git commit after verified changes.", "default": False},
    ],
}

_DEFAULT_MODEL = "gemini-3.8-flash"
_DEFAULT_MAX_ATTEMPTS = 3
_MAX_FILES = 48
_MAX_FILE_CHARS = 18000
_PROTECTED_PARTS = {".git", ".venv", "venv", "env", "__pycache__", "node_modules", "dist", "build"}
_PROTECTED_FILES = {"plugins/self_coding.py", "self_coding_engine/engine.py", "self_coding_engine/__init__.py", "config/api_keys.json"}


def _workspace() -> Path:
    configured = str(get_plugin_setting("self_coding", "workspace", "") or "").strip()
    root = Path(configured).expanduser() if configured else Path(__file__).resolve().parent.parent
    return root.resolve()


def _client() -> genai.Client:
    key = get_gemini_key() or os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("No Gemini API key is configured for Mark 53.")
    return genai.Client(api_key=key)


def _model() -> str:
    return str(get_plugin_setting("self_coding", "model", _DEFAULT_MODEL) or _DEFAULT_MODEL).strip() or _DEFAULT_MODEL


def _json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("The coding model returned no JSON object.")
    return json.loads(text[start : end + 1])


def _ask(system: str, prompt: str) -> dict:
    response = _client().models.generate_content(model=_model(), contents=prompt, config=types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json", max_output_tokens=24000))
    return _json(response.text)


def _inventory(root: Path) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []
    allowed_suffixes = {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".md", ".toml", ".yaml", ".yml"}
    for path in sorted(root.rglob("*")):
        if len(result) >= _MAX_FILES:
            break
        if not path.is_file() or path.suffix.lower() not in allowed_suffixes:
            continue
        rel = path.relative_to(root)
        if any(part.lower() in _PROTECTED_PARTS for part in rel.parts):
            continue
        rel_s = str(rel).replace("\\", "/")
        if rel_s in _PROTECTED_FILES:
            continue
        try:
            data = path.read_text(encoding="utf-8")
        except Exception:
            continue
        result.append({"path": rel_s, "content": data[:_MAX_FILE_CHARS]})
    return result


def _safe_paths(paths: Sequence[str], root: Path) -> tuple[str, ...]:
    safe: list[str] = []
    for raw in paths:
        rel = str(raw).strip().replace("\\", "/")
        if not rel or rel in _PROTECTED_FILES or rel.startswith("/") or ".." in Path(rel).parts:
            raise RuntimeError(f"Unauthorized coding path: {raw}")
        if any(part.lower() in _PROTECTED_PARTS for part in Path(rel).parts):
            raise RuntimeError(f"Unauthorized coding path: {raw}")
        candidate = (root / rel).resolve()
        candidate.relative_to(root)
        safe.append(rel)
    return tuple(dict.fromkeys(safe))


def _planner(goal: str, context: Sequence[Mapping[str, Any]]) -> CodingPlan:
    data = _ask("You are the planning subagent for a production self-coding system. Return JSON only. Break the user's goal into small, testable steps. Every step must list explicit workspace-relative expected_paths. Never use absolute paths, parent traversal, secrets, virtual environments, build output, the self-coding plugin itself, or the self_coding_engine package.", json.dumps({"goal": goal, "workspace_context": list(context)}, ensure_ascii=False))
    steps = []
    for index, item in enumerate(data.get("steps", []), 1):
        paths = _safe_paths(item.get("expected_paths", []), _workspace())
        if not paths:
            continue
        steps.append(CodingStep(id=str(item.get("id") or f"step-{index}"), description=str(item.get("description") or goal), expected_paths=paths, payload={"planner": item}))
    if not steps:
        raise RuntimeError("The coding planner produced no authorized steps.")
    return CodingPlan(goal=goal, steps=tuple(steps))


def _write_operations(data: Mapping[str, Any], root: Path, allowed: Sequence[str]) -> None:
    allowed_set = set(allowed)
    for op in data.get("operations", []):
        path = str(op.get("path", "")).replace("\\", "/")
        if path not in allowed_set:
            raise RuntimeError(f"Model attempted to edit unauthorized path: {path}")
        target = (root / path).resolve()
        target.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        action = str(op.get("action", "write")).lower()
        if action == "delete":
            if target.exists() and target.is_file():
                target.unlink()
        elif action == "write":
            content = op.get("content")
            if not isinstance(content, str):
                raise RuntimeError(f"Missing text content for {path}")
            target.write_text(content, encoding="utf-8", newline="\n")
        else:
            raise RuntimeError(f"Unknown coding operation: {action}")


def _executor(step: CodingStep, root: Path, context: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    files = []
    for rel in step.expected_paths:
        p = root / rel
        files.append({"path": rel, "content": p.read_text(encoding="utf-8")[:_MAX_FILE_CHARS] if p.exists() and p.is_file() else None})
    data = _ask("You are the implementation subagent. Return JSON only. Implement the requested change using complete file contents. You may ONLY write/delete the explicitly authorized paths. Preserve existing behavior unless the goal requires changing it. Do not emit markdown.", json.dumps({"step": step.description, "authorized_paths": step.expected_paths, "files": files}, ensure_ascii=False))
    _write_operations(data, root, step.expected_paths)
    return data


def _run_test_command(root: Path) -> tuple[bool, str]:
    raw = str(get_plugin_setting("self_coding", "test_command", "") or "").strip()
    if raw:
        command, shell = raw, True
    elif (root / "pytest.ini").exists() or (root / "pyproject.toml").exists() or (root / "tests").is_dir():
        command, shell = [os.fspath(os.sys.executable), "-m", "pytest", "-q"], False
    else:
        command, shell = [os.fspath(os.sys.executable), "-m", "compileall", "-q", "."], False
    proc = subprocess.run(command, cwd=root, shell=shell, capture_output=True, text=True, timeout=300, check=False)
    output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    return proc.returncode == 0, output[-12000:]


def _verifier(step: CodingStep, root: Path) -> Mapping[str, Any]:
    for rel in step.expected_paths:
        path = root / rel
        if path.suffix.lower() == ".py" and path.exists():
            try:
                compile(path.read_text(encoding="utf-8"), rel, "exec")
            except Exception as exc:
                return {"success": False, "error": f"Python syntax error in {rel}: {exc}"}
    if not bool(get_plugin_setting("self_coding", "run_tests", True)):
        return {"success": True, "detail": "syntax checks passed; test execution disabled"}
    ok, output = _run_test_command(root)
    return {"success": ok, "output": output}


def _repair(step: CodingStep, attempt: int, previous: Any, root: Path) -> Any:
    data = _ask("You are the repair subagent. Return JSON only. Fix the previous coding attempt using ONLY the authorized paths. Keep the change minimal and preserve behavior. Do not modify the self-coding engine, plugin, secrets, or build environments.", json.dumps({"step": step.description, "attempt": attempt, "authorized_paths": step.expected_paths, "previous_result": previous, "verification": _verifier(step, root)}, ensure_ascii=False))
    _write_operations(data, root, step.expected_paths)
    return data


def _commit(root: Path, goal: str, changed: Sequence[str]) -> str:
    if not changed:
        return ""
    subprocess.run(["git", "-C", str(root), "add", "--", *changed], check=True, capture_output=True, text=True)
    message = "self-coding: " + " ".join(goal.split())[:110]
    proc = subprocess.run(["git", "-C", str(root), "commit", "-m", message], check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "git commit failed").strip())
    return (proc.stdout or "").strip()


def _check_setup(values: dict):
    try:
        workspace = Path(str(values.get("workspace") or "").strip()).expanduser() if str(values.get("workspace") or "").strip() else Path(__file__).resolve().parent.parent
        workspace = workspace.resolve()
        if not workspace.is_dir():
            return False, f"Workspace not found: {workspace}"
        if not (workspace / ".git").is_dir():
            return False, "Workspace is not a Git repository."
        if not (get_gemini_key() or os.getenv("GEMINI_API_KEY")):
            return False, "No Gemini API key is configured."
        return True, f"Self-coding ready — workspace OK, Git OK, Gemini key OK. Tests: {'ON' if values.get('run_tests', True) else 'OFF'}."
    except Exception as exc:
        return False, f"Setup check failed: {exc}"


PLUGIN_SETTINGS["action"] = {"label": "▸ CHECK SETUP", "run": _check_setup}


def run(parameters: dict, player=None, session_memory=None) -> str:
    goal = str(parameters.get("goal", "")).strip()
    if not goal:
        return "Sir, I need a concrete coding objective."
    root = _workspace()
    if not root.is_dir():
        return f"Sir, the configured coding workspace does not exist: {root}"
    try:
        if not (root / ".git").exists():
            return "Sir, I require a git workspace so I can verify and safely track changes."
        context = _inventory(root)
        engine = SelfCodingEngine(planner=_planner, executor=_executor, verifier=_verifier, repairer=_repair, max_attempts=max(1, min(5, int(get_plugin_setting("self_coding", "max_attempts", _DEFAULT_MAX_ATTEMPTS) or _DEFAULT_MAX_ATTEMPTS))))
        completed_steps: list[str] = []
        changed: set[str] = set()
        for event in engine.run(goal, workspace=root, context=context):
            kind, data = event.type, dict(event.data)
            if player:
                try:
                    if kind == "plan":
                        player.write_log(f"JARVIS: Self-coding plan created: {len(data.get('steps', []))} step(s).")
                    elif kind == "attempt_started":
                        player.write_log(f"JARVIS: Coding {data.get('step')} — attempt {data.get('attempt')}.")
                    elif kind == "attempt_failed":
                        player.write_log(f"JARVIS: Coding attempt failed: {data.get('error')}")
                    elif kind == "step_completed":
                        completed_steps.append(str(data.get("step")))
                    elif kind == "attempt_completed":
                        changed.update(map(str, data.get("changed_paths", [])))
                except Exception:
                    pass
        if bool(get_plugin_setting("self_coding", "auto_commit", False)) and changed:
            _commit(root, goal, sorted(changed))
        return f"Completed the self-coding task, sir. {len(completed_steps)} step(s) verified; {len(changed)} file(s) changed."
    except Exception as exc:
        return f"Sir, the self-coding run stopped safely: {exc}"
