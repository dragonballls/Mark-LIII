from __future__ import annotations

from pathlib import Path


def test_browser_setup_exposes_auto_configure(monkeypatch):
    import plugins.browser_setup as plugin

    saved = {}
    monkeypatch.setattr(plugin, "Path", Path)
    monkeypatch.setattr(
        "memory.config_manager.save_plugin_config",
        lambda ns, values: saved.update({"namespace": ns, "values": values}),
    )

    ok, message = plugin._auto_configure({"browser": "edge", "headless": False})
    assert ok is True
    assert "configured automatically" in message
    assert saved["namespace"] == "browser_setup"
    assert saved["values"]["browser"] == "edge"
    assert Path(saved["values"]["profile_dir"]).name == "browser_profile"
    assert plugin.PLUGIN_SETTINGS["action"]["label"].startswith("▸ AUTO-CONFIGURE")


def test_autonomous_provisioner_exposes_auto_configure(monkeypatch):
    import plugins.autonomous_provisioner as plugin

    saved = {}
    monkeypatch.setattr(
        "memory.config_manager.save_plugin_config",
        lambda ns, values: saved.update({"namespace": ns, "values": values}),
    )
    monkeypatch.setattr(
        plugin,
        "provision_all",
        lambda **kwargs: {"status": "ready", "ready": ["ElevenLabs"], "message": "ready"},
    )

    ok, message = plugin._auto_configure({"browser_setup": True})
    assert ok is True
    assert "Ready services: ElevenLabs" in message
    assert saved["namespace"] == "autonomous_provisioner"
    assert saved["values"] == {"enabled": True, "browser_setup": True}


def test_opera_gx_plugin_auto_configures_detected_executable(monkeypatch, tmp_path):
    import plugins.opera_gx as plugin

    executable = tmp_path / "opera.exe"
    executable.write_bytes(b"MZ")
    saved = {}
    monkeypatch.setattr(
        "memory.config_manager.save_plugin_config",
        lambda ns, values: saved.update({"namespace": ns, "values": values}),
    )
    monkeypatch.setattr("actions.opera_gx._find_opera_gx", lambda: str(executable))

    ok, message = plugin._auto_configure({})
    assert ok is True
    assert "Opera GX configured automatically" in message
    assert saved["namespace"] == "opera_gx"
    assert saved["values"]["enabled"] is True
    assert saved["values"]["executable_path"] == str(executable.resolve())
    assert plugin.PLUGIN_SETTINGS["action"]["label"] == "▸ AUTO-CONFIGURE OPERA GX"
