"""Guarded local system control for JARVIS.

Provides conversational control over PowerShell, processes, user files, and
user startup entries. Destructive operations require an explicit confirmation
flag and critical/system processes and locations are blocked.
"""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
from pathlib import Path
from typing import Any

try:
    import psutil
except Exception:  # pragma: no cover - dependency is declared in requirements
    psutil = None

try:
    import send2trash
except Exception:  # pragma: no cover
    send2trash = None


_SYSTEM = platform.system()
_HOME = Path.home().resolve()

_PROTECTED_PROCESSES = {
    "system", "idle", "registry", "smss.exe", "csrss.exe", "wininit.exe",
    "winlogon.exe", "services.exe", "lsass.exe", "svchost.exe", "dwm.exe",
    "secure system", "memory compression", "fontdrvhost.exe", "sihost.exe",
    "explorer.exe", "taskhostw.exe", "ctfmon.exe",
}

_PROTECTED_PATHS = {
    _HOME,
    _HOME / "Desktop",
    _HOME / "Documents",
    _HOME / "Downloads",
    _HOME / "Pictures",
    _HOME / "Music",
    _HOME / "Videos",
}

_READ_ONLY_PS_COMMANDS = {
    "get-process", "get-service", "get-scheduledtask", "get-item", "get-childitem",
    "get-content", "get-command", "get-computerinfo", "get-ciminstance", "get-wmiobject",
    "get-itemproperty", "get-location", "get-date", "get-variable", "get-help",
    "test-path", "resolve-path", "measure-object", "select-object", "where-object",
    "sort-object", "format-table", "format-list", "write-output", "write-host",
    "convertto-json", "compare-object", "hostname", "whoami", "systeminfo",
}

_RISKY_PS_PATTERNS = (
    r"\bremove-item\b", r"\bremove-itemproperty\b", r"\bdel(?:ete)?\b",
    r"\berase\b", r"\brm\b", r"\bformat(?:-volume)?\b", r"\bclear-disk\b",
    r"\bstop-process\b", r"\bstop-service\b", r"\bdisable-scheduledtask\b",
    r"\bremove-scheduledtask\b", r"\bset-itemproperty\b", r"\bset-content\b",
    r"\badd-content\b", r"\bnew-item\b", r"\bcopy-item\b", r"\bmove-item\b",
    r"\brename-item\b", r"\bstart-process\b", r"\bstart-service\b",
    r"\bstop-computer\b", r"\brestart-computer\b", r"\bshutdown\b",
    r"\breg(?:\.exe)?\s+(delete|add|import|copy|load|restore)\b",
    r"\bsc(?:\.exe)?\s+(stop|delete|config|create|failure)\b",
    r"\binvoke-expression\b", r"\biex\b", r"\bdownloadstring\b",
    r"\bpowershell(?:\.exe)?\b.*\s-(?:enc|encodedcommand)\b",
    r"\bcmd(?:\.exe)?\s+/c\b",
)


def _is_windows() -> bool:
    return _SYSTEM == "Windows"


def _safe_user_path(raw: str) -> Path | None:
    """Resolve a path but keep all file deletion inside the user's home tree."""
    try:
        path = Path(str(raw or "").strip()).expanduser().resolve()
        if path == _HOME:
            return None
        if not path.is_relative_to(_HOME):
            return None
        if path in {p.resolve() for p in _PROTECTED_PATHS}:
            return None
        return path
    except Exception:
        return None


def _powershell(command: str, timeout: int = 30) -> tuple[int, str, str]:
    if not _is_windows():
        raise RuntimeError("PowerShell control is only enabled on Windows.")
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        text=True,
        timeout=max(1, min(int(timeout), 120)),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def _powershell_requires_confirmation(command: str) -> bool:
    lower = str(command or "").strip().lower()
    if not lower:
        return False
    if any(re.search(pattern, lower) for pattern in _RISKY_PS_PATTERNS):
        return True
    first = re.match(r"^(?:&\s*)?([a-z0-9_.-]+)", lower)
    if first and first.group(1) in _READ_ONLY_PS_COMMANDS:
        return False
    return True


def _list_processes(query: str = "") -> str:
    if psutil is None:
        return "psutil is unavailable; process inspection cannot run."
    query = str(query or "").strip().lower()
    rows: list[str] = []
    for proc in psutil.process_iter(["pid", "name", "username", "cpu_percent", "memory_info"]):
        try:
            name = str(proc.info.get("name") or "")
            if query and query not in name.lower():
                continue
            mem = proc.info.get("memory_info")
            rss_mb = (float(mem.rss) / 1024 / 1024) if mem else 0.0
            rows.append(f"PID {proc.info.get('pid')}: {name} | RAM {rss_mb:.1f} MB")
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    if not rows:
        return "No matching processes found."
    return "\n".join(rows[:80])


def _stop_process(pid: int | None = None, name: str = "", confirm: bool = False) -> str:
    if psutil is None:
        return "psutil is unavailable; process control cannot run."

    targets: list[Any] = []
    if pid is not None:
        try:
            targets = [psutil.Process(int(pid))]
        except (psutil.NoSuchProcess, ValueError, TypeError):
            return f"Process PID {pid} was not found."
    else:
        wanted = str(name or "").strip().lower()
        if not wanted:
            return "Provide a PID or process name."
        for proc in psutil.process_iter(["name"]):
            try:
                proc_name = str(proc.info.get("name") or "").lower()
                if proc_name == wanted or Path(proc_name).stem == Path(wanted).stem:
                    targets.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue

    safe_targets: list[Any] = []
    for proc in targets:
        try:
            pname = str(proc.name() or "").lower()
            if pname in _PROTECTED_PROCESSES or pname.endswith(".sys"):
                return f"Refused to stop protected system process: {pname}."
            safe_targets.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not safe_targets:
        return "No permitted matching process was found."

    preview = ", ".join(f"{p.pid} ({p.name()})" for p in safe_targets)
    if not confirm:
        return f"Confirmation required before stopping: {preview}. Call stop_process again with confirm=true."

    stopped: list[str] = []
    for proc in safe_targets:
        try:
            proc.terminate()
            stopped.append(f"{proc.pid} ({proc.name()})")
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    return "Stop requested for: " + (", ".join(stopped) if stopped else "none")


def _delete_path(path: str, confirm: bool = False) -> str:
    target = _safe_user_path(path)
    if target is None:
        return "Deletion is limited to non-protected paths inside the current user's home directory."
    if not target.exists():
        return f"Path not found: {path}"
    if not confirm:
        kind = "directory" if target.is_dir() else "file"
        return f"Confirmation required before moving {kind} to the Recycle Bin: {target}. Call delete_path again with confirm=true."
    if send2trash is None:
        return "send2trash is unavailable; permanent deletion is disabled."
    try:
        send2trash.send2trash(str(target))
        return f"Moved to the Recycle Bin: {target}"
    except Exception as exc:
        return f"Could not move to the Recycle Bin: {exc}"


def _startup_folder() -> Path:
    return _HOME / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _list_startup() -> str:
    if not _is_windows():
        return "Startup inspection is currently implemented for Windows."

    lines: list[str] = []
    import winreg

    for hive_name, hive in (("HKCU", winreg.HKEY_CURRENT_USER),):
        for subkey in (r"Software\Microsoft\Windows\CurrentVersion\Run", r"Software\Microsoft\Windows\CurrentVersion\RunOnce"):
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    for i in range(winreg.QueryInfoKey(key)[1]):
                        name, value, _kind = winreg.EnumValue(key, i)
                        lines.append(f"REGISTRY {hive_name}\\{subkey} | {name} = {value}")
            except OSError:
                pass

    startup = _startup_folder()
    if startup.is_dir():
        for item in sorted(startup.iterdir()):
            lines.append(f"STARTUP_FOLDER | {item.name} | {item}")

    try:
        code = "Get-ScheduledTask | Where-Object {$_.State -ne 'Disabled' -and $_.TaskPath -notlike '\\Microsoft\\*'} | ForEach-Object { $_.TaskPath + $_.TaskName }"
        rc, out, _err = _powershell(code, timeout=20)
        if rc == 0:
            for line in out.splitlines():
                if line.strip():
                    lines.append(f"SCHEDULED_TASK | {line.strip()}")
    except Exception:
        pass

    return "\n".join(lines) if lines else "No user startup entries were found."


def _disable_startup(name: str, kind: str = "auto", confirm: bool = False) -> str:
    if not _is_windows():
        return "Startup control is currently implemented for Windows."
    wanted = str(name or "").strip()
    if not wanted:
        return "Provide the startup item name."
    kind = kind if kind in {"auto", "registry", "folder", "scheduled_task"} else "auto"

    import winreg
    matches: list[tuple[str, Any]] = []

    if kind in {"auto", "registry"}:
        for subkey in (r"Software\Microsoft\Windows\CurrentVersion\Run", r"Software\Microsoft\Windows\CurrentVersion\RunOnce"):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey) as key:
                    for i in range(winreg.QueryInfoKey(key)[1]):
                        value_name, value_data, _kind = winreg.EnumValue(key, i)
                        if wanted.lower() in value_name.lower() or wanted.lower() in str(value_data).lower():
                            matches.append((f"registry:{subkey}:{value_name}", (subkey, value_name)))
            except OSError:
                pass

    if kind in {"auto", "folder"}:
        startup = _startup_folder()
        if startup.is_dir():
            for item in startup.iterdir():
                if wanted.lower() in item.name.lower():
                    matches.append((f"folder:{item.name}", item))

    if kind in {"auto", "scheduled_task"}:
        safe_ps = "Get-ScheduledTask | Where-Object {$_.TaskPath -notlike '\\Microsoft\\*'} | ForEach-Object { $_.TaskPath + $_.TaskName }"
        try:
            rc, out, _err = _powershell(safe_ps, timeout=20)
            if rc == 0:
                for task in out.splitlines():
                    task = task.strip()
                    if task and wanted.lower() in task.lower() and not task.lower().startswith("\\microsoft\\"):
                        matches.append((f"task:{task}", task))
        except Exception:
            pass

    if not matches:
        return f"No user startup entry matched '{wanted}'."

    preview = ", ".join(label for label, _ in matches[:12])
    if not confirm:
        return f"Confirmation required before disabling startup entry: {preview}. Call disable_startup again with confirm=true."

    changed: list[str] = []
    for label, target in matches:
        try:
            if label.startswith("registry:"):
                subkey, value_name = target
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_SET_VALUE) as key:
                    winreg.DeleteValue(key, value_name)
                changed.append(label)
            elif label.startswith("folder:") and isinstance(target, Path):
                if send2trash is None:
                    continue
                send2trash.send2trash(str(target))
                changed.append(label)
            elif label.startswith("task:"):
                task_name = str(target)
                rc, _out, _err = _powershell(
                    f"Disable-ScheduledTask -TaskName {json.dumps(task_name)} -ErrorAction Stop | Out-Null",
                    timeout=20,
                )
                if rc == 0:
                    changed.append(label)
        except Exception:
            continue

    return "Disabled startup entries: " + (", ".join(changed) if changed else "none")


def run_system_control(parameters: dict, player=None, **_: Any) -> str:
    action = str((parameters or {}).get("action", "")).strip().lower()
    confirm = bool((parameters or {}).get("confirm", False))

    if action == "list_processes":
        return _list_processes(str((parameters or {}).get("query", "") or ""))
    if action == "stop_process":
        pid_raw = (parameters or {}).get("pid")
        try:
            pid = int(pid_raw) if pid_raw not in (None, "") else None
        except (TypeError, ValueError):
            return "PID must be a number."
        return _stop_process(pid=pid, name=str((parameters or {}).get("name", "") or ""), confirm=confirm)
    if action == "delete_path":
        return _delete_path(str((parameters or {}).get("path", "") or ""), confirm=confirm)
    if action == "list_startup":
        return _list_startup()
    if action == "disable_startup":
        return _disable_startup(
            str((parameters or {}).get("name", "") or ""),
            kind=str((parameters or {}).get("kind", "auto") or "auto").lower(),
            confirm=confirm,
        )
    if action == "run_powershell":
        command = str((parameters or {}).get("command", "") or "").strip()
        if not command:
            return "No PowerShell command was provided."
        if _powershell_requires_confirmation(command) and not confirm:
            return "Confirmation required before running this potentially mutating or unknown PowerShell command. Call run_powershell again with confirm=true."
        try:
            rc, out, err = _powershell(command, int((parameters or {}).get("timeout", 30) or 30))
            text = out or err or "(no output)"
            return f"PowerShell exit code {rc}:\n{text[:12000]}"
        except Exception as exc:
            return f"PowerShell command failed safely: {exc}"

    return "Unknown system_control action. Use list_processes, stop_process, delete_path, list_startup, disable_startup, or run_powershell."


TOOL = {
    "name": "system_control",
    "description": (
        "Controlled Windows system administration for the user's own computer. "
        "Use it to inspect processes and startup entries, stop a specified user process, "
        "move a specified user file/folder to the Recycle Bin, disable a specified user startup entry, "
        "or execute PowerShell. Read-only PowerShell commands may run directly; mutating or unknown commands and other destructive actions require confirm=true. "
        "Never stop protected Windows system processes or delete protected user root folders."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["list_processes", "stop_process", "delete_path", "list_startup", "disable_startup", "run_powershell"],
                "description": "Requested system operation.",
            },
            "query": {"type": "STRING", "description": "Optional process-name filter for list_processes."},
            "pid": {"type": "INTEGER", "description": "Process ID for stop_process."},
            "name": {"type": "STRING", "description": "Process or startup entry name."},
            "path": {"type": "STRING", "description": "User-home file or folder path for delete_path."},
            "kind": {"type": "STRING", "enum": ["auto", "registry", "folder", "scheduled_task"], "description": "Startup source to inspect or change."},
            "command": {"type": "STRING", "description": "PowerShell command to run on Windows."},
            "timeout": {"type": "INTEGER", "description": "PowerShell timeout in seconds, capped at 120."},
            "confirm": {"type": "BOOLEAN", "description": "Explicit confirmation for destructive or potentially mutating operations."},
        },
        "required": ["action"],
    },
    "handler": run_system_control,
}
