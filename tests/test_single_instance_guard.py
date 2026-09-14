from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "sitecustomize.py").read_text(encoding="utf-8")


def test_single_instance_guard_targets_jarvis_main_only():
    assert '_MUTEX_NAME = r"Local\\MarkLIII.JARVIS.Singleton"' in SOURCE
    assert 'entry != "main.py"' in SOURCE
    assert "CreateMutexW" in SOURCE
    assert "ERROR_ALREADY_EXISTS" in SOURCE
    assert "raise SystemExit(0)" in SOURCE


def test_single_instance_guard_fails_closed():
    assert "Fail closed" in SOURCE
    assert "raise SystemExit(f\"JARVIS singleton guard unavailable:" in SOURCE
