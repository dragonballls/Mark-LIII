from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "actions" / "opera_gx.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("actions.opera_gx_test", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tool_is_discoverable():
    module = _load_module()
    assert module.TOOL["name"] == "opera_gx"
    assert callable(module.TOOL["handler"])
    assert set(module.TOOL["parameters"]["properties"]["action"]["enum"]) == {"launch", "open", "search"}


def test_desktop_scan_finds_custom_opera_exe(tmp_path):
    module = _load_module()
    desktop = tmp_path / "Desktop"
    custom = desktop / "Microsoft accounts"
    custom.mkdir(parents=True)
    exe = custom / "opera.exe"
    exe.write_bytes(b"MZ")

    with patch.object(module, "_running_opera_gx", return_value=None), patch.object(module.Path, "home", return_value=tmp_path), patch.dict(module.os.environ, {"OneDrive": str(tmp_path / "MissingOneDrive")}, clear=False):
        found = module._find_opera_gx()

    assert found == str(exe)


def test_open_launches_native_executable_without_console():
    module = _load_module()
    with patch.object(module, "_running_opera_gx", return_value=None), patch.object(module, "_find_opera_gx", return_value=r"C:\Opera GX\opera.exe"), patch.object(module.subprocess, "Popen") as popen:
        result = module.run({"action": "open", "url": "github.com"})

    assert result == "Opened in your existing Opera GX: https://github.com"
    popen.assert_called_once()
    command = popen.call_args.args[0]
    assert command == [r"C:\Opera GX\opera.exe", "https://github.com"]
    assert popen.call_args.kwargs["stdin"] is module.subprocess.DEVNULL
    assert popen.call_args.kwargs["stdout"] is module.subprocess.DEVNULL
    assert popen.call_args.kwargs["stderr"] is module.subprocess.DEVNULL


def test_running_opera_is_preferred_over_configured_copy():
    module = _load_module()
    running = r"C:\Users\smart\Opera GX\opera.exe"
    configured = r"C:\Other\Opera GX\opera.exe"
    with patch.object(module, "_running_opera_gx", return_value=running), patch.object(module, "_find_opera_gx", return_value=configured):
        assert module._configured_executable() == running


def test_search_builds_google_query():
    module = _load_module()
    with patch.object(module, "_running_opera_gx", return_value=None), patch.object(module, "_find_opera_gx", return_value=r"C:\Opera GX\opera.exe"), patch.object(module.subprocess, "Popen") as popen:
        result = module.run({"action": "search", "query": "GitHub actions"})

    assert "GitHub actions" in result
    assert popen.call_args.args[0][1] == "https://www.google.com/search?q=GitHub+actions"
