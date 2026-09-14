from __future__ import annotations

import importlib
import os
from unittest.mock import patch

import core.hive_mind as hive


def _spec(name: str, provider: str = "gemini", role: str = "general", project: str = "p1") -> hive.AgentSpec:
    return hive.AgentSpec(name=name, provider=provider, model="test-model", api_key=f"key-{name}", role=role, project=project)


def test_numbered_gemini_keys_are_loaded_without_logging_or_duplication(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(hive, "_load_local_config", lambda: {})
    monkeypatch.setenv("GEMINI_API_KEY_1", "secret-a")
    monkeypatch.setenv("GEMINI_API_KEY_2", "secret-b")

    specs = hive.load_agent_specs()

    assert [item.name for item in specs] == ["gemini-1", "gemini-2"]
    assert [item.api_key for item in specs] == ["secret-a", "secret-b"]


def test_configured_agents_can_use_env_key_names(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_1", raising=False)
    monkeypatch.setattr(
        hive,
        "_load_local_config",
        lambda: {
            "hive_mind": {
                "agents": [
                    {
                        "name": "architect",
                        "provider": "gemini",
                        "model": "test-model",
                        "api_key_env": "HIVE_TEST_KEY",
                        "role": "architecture",
                        "project": "project-a",
                    }
                ]
            }
        },
    )
    monkeypatch.setenv("HIVE_TEST_KEY", "super-secret")

    specs = hive.load_agent_specs()

    assert len(specs) == 1
    assert specs[0].name == "architect"
    assert specs[0].role == "architecture"
    assert specs[0].project == "project-a"
    assert specs[0].api_key == "super-secret"


def test_quota_group_is_shared_by_agents_in_same_project():
    a = _spec("a", project="same-project")
    b = _spec("b", project="same-project")
    c = _spec("c", project="other-project")

    assert a.quota_group == b.quota_group
    assert a.quota_group != c.quota_group


def test_hive_runs_agents_in_parallel_and_summarizes(monkeypatch):
    specs = [_spec("one"), _spec("two"), _spec("three")]
    monkeypatch.setattr(hive, "load_agent_specs", lambda: specs)

    def fake_invoke(agent, prompt, timeout):
        assert "assigned role" in prompt.lower()
        return f"Report from {agent.name}"

    monkeypatch.setattr(hive, "_invoke", fake_invoke)

    result = hive.run_hive("Compare three approaches", max_agents=3, synthesize=False)
    text = hive.summarize(result)

    assert len(result.successful) == 3
    assert "3/3 agents responded successfully" in text
    assert "Report from one" in text
    assert "Report from two" in text
    assert "Report from three" in text


def test_failed_agent_does_not_abort_other_agents(monkeypatch):
    specs = [_spec("good"), _spec("bad")]
    monkeypatch.setattr(hive, "load_agent_specs", lambda: specs)

    def fake_invoke(agent, prompt, timeout):
        if agent.name == "bad":
            raise RuntimeError("429 rate limited")
        return "good answer"

    monkeypatch.setattr(hive, "_invoke", fake_invoke)

    result = hive.run_hive("test", max_agents=2, synthesize=False)

    assert len(result.successful) == 1
    assert result.results[0].name == "bad"
    assert result.results[1].name == "good"
    assert result.results[0].ok is False
    assert "429" in result.results[0].error


def test_gemini_request_uses_header_not_url_key(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "hello from gemini"}]}}
                ]
            }

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(hive.requests, "post", fake_post)
    text = hive._call_gemini(_spec("g", provider="gemini"), "prompt", 10)

    assert text == "hello from gemini"
    assert "key-" not in calls[0][0]
    assert calls[0][1]["headers"]["x-goog-api-key"] == "key-g"
