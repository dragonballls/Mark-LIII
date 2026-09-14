from __future__ import annotations

from pathlib import Path

import core.self_updater as updater


def test_dirty_worktree_defers_update(monkeypatch):
    monkeypatch.setattr(updater, "_clean_tree", lambda: False)
    monkeypatch.setattr(updater, "_ensure_remote", lambda logger=None: (_ for _ in ()).throw(AssertionError("remote should not be touched")))

    result = updater.check_and_update(restart=False)

    assert result["status"] == "deferred"
    assert result["updated"] is False


def test_remote_is_the_user_fork():
    assert updater.REPOSITORY_URL == "https://github.com/dragonballls/Mark-LIII.git"
    assert updater.REMOTE == "origin"
    assert updater.BRANCH == "main"


def test_runtime_bootstrap_only_targets_real_entrypoints():
    source = Path("core/__init__.py").read_text(encoding="utf-8")
    assert "MARK_DISABLE_AUTO_UPDATE" in source
    assert "main.py" in source
    assert "pytest" not in source


def test_updater_has_restart_handoff_and_no_legacy_state_name():
    source = Path("core/self_updater.py").read_text(encoding="utf-8")
    assert "JARVIS_RESTART_HANDOFF" in source
    assert "mark-pre-update-" in source
    assert ".mark_update_state.json" in source
    assert ".jarvis_update_state.json" not in source
