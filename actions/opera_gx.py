"""Safe native launcher for the user's Opera GX browser.

This action is intentionally separate from self-coding, browser setup, and the
interactive Playwright browser controller. It opens targets through the user's
already-running Opera GX instance when possible, preserving the normal profile,
sign-ins, extensions, and existing browser process.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote_plus


TOOL = {
    "name": "opera_gx",
    "description": (
        "Open websites and searches in the user's existing Opera GX browser instance. "
        "Prefer the already-running Opera GX process rather than starting a separate browser instance. "
        "Preserves the user's normal Opera GX profile, sign-ins, and extensions."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "launch | open | search",
                "enum": ["launch", "open", "search"],
            },
            "url": {
                "type": "STRING",
                "description": "Website URL to open in Opera GX.",
            },
            "query": {
                "type": "STRING",
                "description": "Search query to run in Opera GX.",
            },
        },
        "required": ["action"],
    },
    "handler": None,
}


def _candidate_dirs() -> list[Path]:
    home = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    program_files = Path(os.environ.get("PROGRAMFILES", ""))
    program_files_x86 = Path(os.environ.get("PROGRAMFILES(X86)", ""))
    roaming = Path(os.environ.get("APPDATA", ""))

    candidates = [
        local / "Programs" / "Opera GX" / "opera.exe",
        local / "Programs" / "Opera" / "opera.exe",
        roaming / "Opera Software" / "Opera GX Stable" / "opera.exe",
        local / "Opera Software" / "Opera GX Stable" / "opera.exe",
        program_files / "Opera GX" / "opera.exe",
        program_files / "Opera" / "opera.exe",
        program_files_x86 / "Opera GX" / "opera.exe",
        program_files_x86 / "Opera" / "opera.exe",
    ]

    desktop_roots = {
        home / "Desktop",
        home / "OneDrive" / "Desktop",
    }
    for env_name in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        raw = os.environ.get(env_name)
        if raw:
            desktop_roots.add(Path(raw) / "Desktop")

    for root in desktop_roots:
        if not root.is_dir():
            continue
        for base, dirs, files in os.walk(root):
            depth = len(Path(base).relative_to(root).parts)
            if depth >= 4:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d.lower() not in {"node_modules", ".git", "venv", ".venv", "cache", "caches"}]
            for filename in files:
                if filename.lower() == "opera.exe":
                    candidates.append(Path(base) / filename)

    return candidates


def _running_opera_gx() -> str | None:
    """Return the executable path of an already-running Opera process, if any."""
    try:
        import psutil  # type: ignore
    except Exception:
        return None

    try:
        for proc in psutil.process_iter(["name", "exe"]):
            try:
                name = str(proc.info.get("name") or "").lower()
                exe = str(proc.info.get("exe") or "").strip()
                if name == "opera.exe" and exe and Path(exe).is_file():
                    return exe
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
    except Exception:
        return None
    return None


def _registry_executable() -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg
        keys = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\opera.exe",
            r"SOFTWARE\Clients\StartMenuInternet\OperaGXStable\shell\open\command",
            r"SOFTWARE\Clients\StartMenuInternet\OperaGX\shell\open\command",
            r"SOFTWARE\Clients\StartMenuInternet\OperaStable\shell\open\command",
        ]
        for key_path in keys:
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(hive, key_path) as key:
                        value = str(winreg.QueryValue(key) or "")
                except OSError:
                    continue
                match = re.match(r'\s*"([^"]+\.exe)"', value, flags=re.I)
                candidate = match.group(1) if match else value.split(" --", 1)[0].strip().strip('"')
                if candidate and Path(candidate).is_file():
                    return candidate
    except Exception:
        return None
    return None


def _find_opera_gx() -> str | None:
    running = _running_opera_gx()
    if running:
        return running

    seen: set[str] = set()
    for candidate in _candidate_dirs():
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            if candidate.is_file() and candidate.suffix.lower() == ".exe":
                return str(candidate)
        except OSError:
            continue

    registry_path = _registry_executable()
    if registry_path:
        return registry_path
    return shutil.which("opera.exe") or shutil.which("opera")


def _configured_executable() -> str | None:
    try:
        from memory.config_manager import get_plugin_setting, save_plugin_config
        if not bool(get_plugin_setting("opera_gx", "enabled", True)):
            return None

        # Always prefer the currently running Opera GX process, even when an
        # older configured path points at another copy of opera.exe.
        running = _running_opera_gx()
        if running:
            save_plugin_config("opera_gx", {"enabled": True, "executable_path": running})
            return running

        configured = str(get_plugin_setting("opera_gx", "executable_path", "") or "").strip()
        if configured and Path(configured).is_file():
            return configured
        discovered = _find_opera_gx()
        if discovered:
            save_plugin_config("opera_gx", {"enabled": True, "executable_path": discovered})
        return discovered
    except Exception:
        return _find_opera_gx()


def _normalize_url(url: str) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    if "://" in value:
        return value
    if value.startswith(("www.", "localhost", "127.0.0.1")) or "." in value:
        return "https://" + value
    return "https://" + value + ".com"


def run(parameters: dict, player=None, speak=None, response=None, session_memory=None) -> str:
    action = str(parameters.get("action", "") or "").strip().lower()
    if action not in {"launch", "open", "search"}:
        return "Unknown Opera GX action. Use launch, open, or search."

    try:
        from memory.config_manager import get_plugin_setting
        if not bool(get_plugin_setting("opera_gx", "enabled", True)):
            return "Opera GX integration is disabled in Plugin Settings."
    except Exception:
        pass

    executable = _configured_executable()
    if not executable:
        return "Opera GX executable was not found on this computer."

    target = ""
    if action == "open":
        target = _normalize_url(parameters.get("url", ""))
        if not target:
            return "No URL was provided for Opera GX."
    elif action == "search":
        query = str(parameters.get("query", "") or "").strip()
        if not query:
            return "No search query was provided for Opera GX."
        target = "https://www.google.com/search?q=" + quote_plus(query)

    try:
        # Passing a URL to the already-running Opera executable uses Opera's
        # normal single-instance routing on Windows, so the target opens in the
        # existing browser rather than launching a second independent profile.
        command = [executable] + ([target] if target else [])
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        return f"Opera GX could not be launched: {exc}"

    if action == "launch":
        return "Opera GX is ready."
    if action == "search":
        return f"Opened the search in your existing Opera GX: {parameters.get('query', '').strip()}"
    return f"Opened in your existing Opera GX: {target}"


TOOL["handler"] = run
