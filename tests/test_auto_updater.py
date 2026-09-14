from __future__ import annotations

from pathlib import Path

import core.self_updater as updater


def test_dirty_worktree_defers_update(monkeypatch):
    monkeypatch.setattr(updater, "_clean_tree", lambda: False)
    monkeypatch.setattr(
        updater,
        "_ensure_remote",
        lambda logger=None: (_ for _ in ()).throw(AssertionError("remote should not be touched")),
    )

    result = updater.check_and_update(restart=False)

    assert result["status"] == "deferred"
    assert result["updated"] is False


def test_remote_is_the_official_creator_repo():
    assert updater.REPOSITORY_URL == "https://github.com/FatihMakes/Mark-LIII.git"
    assert updater.REMOTE == "upstream"
    assert updater.BRANCH == "main"


def test_revision_plan_current(monkeypatch):
    monkeypatch.setattr(updater, "_run", lambda *args, **kwargs: None)
    assert updater._revision_plan("same", "same") == "current"


def test_revision_plan_fast_forward(monkeypatch):
    class Result:
        def __init__(self, returncode):
            self.returncode = returncode

    calls = iter([Result(0)])
    monkeypatch.setattr(updater, "_run", lambda *args, **kwargs: next(calls))
    assert updater._revision_plan("local", "official") == "fast_forward"


def test_revision_plan_local_ahead(monkeypatch):
    class Result:
        def __init__(self, returncode):
            self.returncode = returncode

    calls = iter([Result(1), Result(0)])
    monkeypatch.setattr(updater, "_run", lambda *args, **kwargs: next(calls))
    assert updater._revision_plan("local", "official") == "current"


def test_revision_plan_diverged_requires_merge(monkeypatch):
    class Result:
        def __init__(self, returncode):
            self.returncode = returncode

    calls = iter([Result(1), Result(1)])
    monkeypatch.setattr(updater, "_run", lambda *args, **kwargs: next(calls))
    assert updater._revision_plan("local", "official") == "merge"


def test_runtime_bootstrap_only_targets_real_entrypoints():
    source = Path("core/__init__.py").read_text(encoding="utf-8")
    assert "MARK_DISABLE_AUTO_UPDATE" in source
    assert "main.py" in source
    assert "pytest" not in source


def test_updater_has_restart_handoff_and_official_source_guard():
    source = Path("core/self_updater.py").read_text(encoding="utf-8")
    assert "JARVIS_RESTART_HANDOFF" in source
    assert "mark-pre-update-" in source
    assert ".mark_update_state.json" in source
    assert ".jarvis_update_state.json" not in source
    assert "https://github.com/FatihMakes/Mark-LIII.git" in source
    assert "https://github.com/dragonballls/Mark-LIII.git" not in source


def test_updater_preserves_user_fork_as_origin():
    source = Path("core/self_updater.py").read_text(encoding="utf-8")
    assert 'REMOTE = "upstream"' in source
    assert 'REMOTE = "origin"' not in source
