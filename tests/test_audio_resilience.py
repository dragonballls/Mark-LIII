from __future__ import annotations

from types import SimpleNamespace


def test_windows_live_output_gets_high_latency_only(monkeypatch):
    import core.audio_resilience as audio

    class FakeStream:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    fake_sd = SimpleNamespace(RawOutputStream=FakeStream)
    monkeypatch.setattr(audio.platform, "system", lambda: "Windows")

    assert audio.install_output_latency_guard(fake_sd) is True

    live = fake_sd.RawOutputStream(samplerate=24000, blocksize=1024)
    assert live.kwargs["latency"] == "high"


def test_existing_latency_and_other_rates_are_untouched(monkeypatch):
    import importlib
    import core.audio_resilience as audio

    audio = importlib.reload(audio)

    class FakeStream:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    fake_sd = SimpleNamespace(RawOutputStream=FakeStream)
    monkeypatch.setattr(audio.platform, "system", lambda: "Windows")
    assert audio.install_output_latency_guard(fake_sd) is True

    explicit = fake_sd.RawOutputStream(samplerate=24000, latency="low")
    other_rate = fake_sd.RawOutputStream(samplerate=48000)
    assert explicit.kwargs["latency"] == "low"
    assert "latency" not in other_rate.kwargs
