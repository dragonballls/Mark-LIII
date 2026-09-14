from __future__ import annotations

import actions.check_for_updates as action


def test_repeated_manual_checks_are_deduplicated(monkeypatch):
    calls = []

    def fake_check_and_update(*, logger=None, restart=True):
        calls.append((logger, restart))
        if logger:
            logger("[MarkUpdater] Already current with the official FatihMakes/Mark-LIII main.")
        return {
            "updated": False,
            "status": "current",
            "message": "Already current with the official FatihMakes/Mark-LIII main.",
        }

    monkeypatch.setattr(action, "check_and_update", fake_check_and_update)
    monkeypatch.setattr(action, "_LAST_CHECK_AT", 0.0)
    monkeypatch.setattr(action, "_LAST_RESULT", None)

    first = action.check_for_updates({}, speak=None)
    second = action.check_for_updates({}, speak=None)

    assert first == second
    assert len(calls) == 1
