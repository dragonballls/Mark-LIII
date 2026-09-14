from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "actions" / "system_control.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("actions.system_control_test", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tool_is_discoverable_with_expected_actions():
    module = _load_module()
    assert module.TOOL["name"] == "system_control"
    assert callable(module.TOOL["handler"])
    assert set(module.TOOL["parameters"]["properties"]["action"]["enum"]) == {
        "list_processes", "stop_process", "delete_path", "list_startup",
        "disable_startup", "run_powershell",
    }


def test_stop_process_requires_confirmation():
    module = _load_module()

    class FakeProc:
        pid = 3210

        def name(self):
            return "example.exe"

        def terminate(self):
            raise AssertionError("terminate must not run during preview")

    fake = FakeProc()
    with patch.object(module, "psutil") as psutil_mock:
        psutil_mock.NoSuchProcess = RuntimeError
        psutil_mock.AccessDenied = RuntimeError
        psutil_mock.process_iter.return_value = iter([fake])
        result = module._stop_process(name="example.exe", confirm=False)

    assert "Confirmation required" in result


def test_delete_path_rejects_protected_user_roots():
    module = _load_module()
    assert module._safe_user_path(str(module._HOME)) is None
    assert module._safe_user_path(str(module._HOME / "Desktop")) is None


def test_delete_path_previews_before_recycle_bin():
    module = _load_module()
    with patch.object(module, "send2trash") as trash:
        with patch.object(module.Path, "exists", return_value=True):
            result = module._delete_path(str(module._HOME / "example.tmp"), confirm=False)
    assert "Confirmation required" in result
    trash.send2trash.assert_not_called()


def test_powershell_risky_commands_require_confirmation():
    module = _load_module()
    assert module._powershell_requires_confirmation("Stop-Process -Name notepad")
    assert module._powershell_requires_confirmation("Remove-Item test.txt")
    assert not module._powershell_requires_confirmation("Get-Process")


def test_powershell_preview_does_not_execute_risky_command():
    module = _load_module()
    with patch.object(module, "_powershell") as runner:
        result = module.run_system_control({
            "action": "run_powershell",
            "command": "Stop-Process -Name notepad",
            "confirm": False,
        })
    assert "Confirmation required" in result
    runner.assert_not_called()


def test_protected_process_is_refused():
    module = _load_module()

    class FakeProc:
        pid = 4

        def name(self):
            return "System"

    with patch.object(module, "psutil") as psutil_mock:
        psutil_mock.NoSuchProcess = RuntimeError
        psutil_mock.AccessDenied = RuntimeError
        psutil_mock.process_iter.return_value = iter([FakeProc()])
        result = module._stop_process(name="System", confirm=True)

    assert "protected system process" in result.lower()
