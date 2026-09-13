from pathlib import Path

from plugins import self_coding


def test_plugin_metadata_and_settings_are_declared() -> None:
    assert self_coding.PLUGIN["name"] == "self_coding"
    assert self_coding.PLUGIN["parameters"]["required"] == ["goal"]
    assert self_coding.PLUGIN_SETTINGS["namespace"] == "self_coding"
    fields = {field["key"]: field for field in self_coding.PLUGIN_SETTINGS["fields"]}
    assert {"workspace", "model", "max_attempts", "run_tests", "test_command", "auto_commit"} <= set(fields)
    assert fields["run_tests"]["type"] == "toggle"
    assert fields["auto_commit"]["type"] == "toggle"
    assert self_coding.PLUGIN_SETTINGS["action"]["label"] == "▸ CHECK SETUP"


def test_safe_paths_reject_escape_and_protected_files(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    assert self_coding._safe_paths(["core/example.py"], root) == ("core/example.py",)
    for bad in ("../outside.py", "/absolute.py", "plugins/self_coding.py", "self_coding_engine/engine.py", ".venv/x.py"):
        try:
            self_coding._safe_paths([bad], root)
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"unsafe path accepted: {bad}")


def test_workspace_defaults_to_plugin_parent(monkeypatch) -> None:
    monkeypatch.setattr(self_coding, "get_plugin_setting", lambda namespace, key, default=None: default)
    assert self_coding._workspace() == Path(self_coding.__file__).resolve().parent.parent
