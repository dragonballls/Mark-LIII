from __future__ import annotations

"""Isolated multi-agent orchestration for JARVIS.

The hive is deliberately separate from self-coding and the live voice loop. It can
fan a user goal out to several explicitly configured hosted providers, collect their
independent answers, and optionally ask one configured member to synthesize them.

Credentials are read only from the existing local config file or environment; they
are never logged or returned. Provider quotas remain the provider's responsibility.
In particular, multiple Gemini API keys from the same Google Cloud project share the
project's rate limits and therefore do not multiply quota.
"""

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests


DEFAULT_MAX_AGENTS = 6
DEFAULT_TIMEOUT = 25
MAX_CONFIGURED_AGENTS = 32
MAX_RESPONSE_CHARS = 12000


@dataclass(frozen=True)
class AgentSpec:
    name: str
    provider: str
    model: str
    api_key: str
    base_url: str = ""
    project: str = ""
    role: str = "general"
    enabled: bool = True

    @property
    def quota_group(self) -> str:
        return self.project or f"{self.provider}:{self.base_url or 'default'}"


@dataclass
class AgentResult:
    name: str
    provider: str
    role: str
    ok: bool
    text: str = ""
    error: str = ""
    latency_ms: int = 0


@dataclass
class HiveResult:
    goal: str
    results: list[AgentResult] = field(default_factory=list)
    synthesis: str = ""

    @property
    def successful(self) -> list[AgentResult]:
        return [item for item in self.results if item.ok and item.text.strip()]


def _load_local_config() -> dict[str, Any]:
    try:
        from config import get_config

        data = get_config()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _env_key(prefix: str, index: int) -> str:
    return os.getenv(f"{prefix}_{index}", "").strip()


def load_agent_specs() -> list[AgentSpec]:
    """Load only explicitly configured, authorized AI endpoints."""
    config = _load_local_config()
    hive = config.get("hive_mind") if isinstance(config.get("hive_mind"), dict) else {}
    raw_agents = hive.get("agents") if isinstance(hive.get("agents"), list) else []
    specs: list[AgentSpec] = []

    # Legacy single Gemini key already used by JARVIS.
    legacy_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not legacy_key:
        legacy_key = str(config.get("gemini_api_key", "") or "").strip()
    legacy_model = str(hive.get("default_gemini_model", "gemini-2.5-flash") or "gemini-2.5-flash")
    if legacy_key:
        specs.append(
            AgentSpec(
                name="gemini-primary",
                provider="gemini",
                model=legacy_model,
                api_key=legacy_key,
                project=str(hive.get("gemini_project", "") or ""),
                role="lead",
            )
        )

    for idx, raw in enumerate(raw_agents[:MAX_CONFIGURED_AGENTS], 1):
        if not isinstance(raw, dict):
            continue
        provider = str(raw.get("provider", "")).strip().lower()
        name = str(raw.get("name", f"agent-{idx}")).strip() or f"agent-{idx}"
        model = str(raw.get("model", "")).strip()
        env_name = str(raw.get("api_key_env", "")).strip()
        key = os.getenv(env_name, "").strip() if env_name else str(raw.get("api_key", "") or "").strip()
        if not provider or not model or not key:
            continue
        specs.append(
            AgentSpec(
                name=name,
                provider=provider,
                model=model,
                api_key=key,
                base_url=str(raw.get("base_url", "") or "").strip(),
                project=str(raw.get("project", "") or "").strip(),
                role=str(raw.get("role", "general") or "general").strip(),
                enabled=bool(raw.get("enabled", True)),
            )
        )

    # Explicit numbered Gemini keys are convenient for a local env-file setup.
    seen = {spec.api_key for spec in specs}
    for idx in range(1, MAX_CONFIGURED_AGENTS + 1):
        key = _env_key("GEMINI_API_KEY", idx)
        if not key or key in seen:
            continue
        specs.append(
            AgentSpec(
                name=f"gemini-{idx}",
                provider="gemini",
                model=legacy_model,
                api_key=key,
                project=os.getenv("GEMINI_PROJECT", "").strip(),
                role="general",
            )
        )
        seen.add(key)

    return [spec for spec in specs if spec.enabled]


def _extract_json_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    first = candidates[0]
    if not isinstance(first, dict):
        return ""
    content = first.get("content")
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts")
    if not isinstance(parts, list):
        return ""
    text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
    return text.strip()[:MAX_RESPONSE_CHARS]


def _call_gemini(agent: AgentSpec, prompt: str, timeout: int) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{agent.model}:generateContent"
    response = requests.post(
        url,
        headers={"x-goog-api-key": agent.api_key, "content-type": "application/json"},
        json={"contents": [{"role": "user", "parts": [{"text": prompt}]}]},
        timeout=timeout,
    )
    response.raise_for_status()
    text = _extract_json_text(response.json())
    if not text:
        raise RuntimeError("Gemini returned no text candidate")
    return text


def _call_openai_compat(agent: AgentSpec, prompt: str, timeout: int) -> str:
    base = agent.base_url.rstrip("/")
    if not base:
        raise RuntimeError("OpenAI-compatible provider is missing base_url")
    url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    response = requests.post(
        url,
        headers={"authorization": f"Bearer {agent.api_key}", "content-type": "application/json"},
        json={
            "model": agent.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise RuntimeError("OpenAI-compatible provider returned no choices")
    message = choices[0].get("message") or {}
    text = str(message.get("content", "") or "").strip()
    if not text:
        raise RuntimeError("Provider returned no text")
    return text[:MAX_RESPONSE_CHARS]


def _call_anthropic(agent: AgentSpec, prompt: str, timeout: int) -> str:
    response = requests.post(
        (agent.base_url or "https://api.anthropic.com").rstrip("/") + "/v1/messages",
        headers={
            "x-api-key": agent.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={"model": agent.model, "max_tokens": 2048, "messages": [{"role": "user", "content": prompt}]},
        timeout=timeout,
    )
    response.raise_for_status()
    content = response.json().get("content")
    if not isinstance(content, list):
        raise RuntimeError("Anthropic returned no content")
    text = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    if not text.strip():
        raise RuntimeError("Anthropic returned no text")
    return text.strip()[:MAX_RESPONSE_CHARS]


def _invoke(agent: AgentSpec, prompt: str, timeout: int) -> str:
    if agent.provider == "gemini":
        return _call_gemini(agent, prompt, timeout)
    if agent.provider in {"openai", "openai-compatible", "deepseek", "custom"}:
        return _call_openai_compat(agent, prompt, timeout)
    if agent.provider == "anthropic":
        return _call_anthropic(agent, prompt, timeout)
    raise RuntimeError(f"Unsupported provider '{agent.provider}'")


def _agent_prompt(goal: str, role: str) -> str:
    return (
        "You are one member of a multi-agent JARVIS hive. Work independently and do not assume "
        "another agent has completed the task. Be concise but concrete. Do not perform external "
        "actions; return analysis/recommendations only.\n\n"
        f"Assigned role: {role}\n"
        f"Goal: {goal}"
    )


def _synthesis_prompt(goal: str, answers: list[AgentResult]) -> str:
    joined = "\n\n".join(
        f"[{item.name} | {item.provider} | {item.role}]\n{item.text}" for item in answers
    )
    return (
        "You are the lead intelligence of JARVIS. Synthesize independent agent reports into one "
        "accurate answer. Resolve contradictions explicitly, prefer claims supported by multiple "
        "agents, and do not invent missing facts. Return only the final answer.\n\n"
        f"Original goal:\n{goal}\n\nAgent reports:\n{joined}"
    )


def run_hive(goal: str, max_agents: int = DEFAULT_MAX_AGENTS, synthesize: bool = True, timeout: int = DEFAULT_TIMEOUT) -> HiveResult:
    specs = load_agent_specs()
    if not specs:
        return HiveResult(goal=goal, results=[AgentResult("hive", "system", "lead", False, error="No AI agents are configured.")])

    selected = specs[: max(1, min(int(max_agents), len(specs)))]
    started = time.perf_counter()
    result = HiveResult(goal=goal)
    lock = threading.Lock()

    def worker(agent: AgentSpec) -> AgentResult:
        t0 = time.perf_counter()
        try:
            text = _invoke(agent, _agent_prompt(goal, agent.role), timeout)
            return AgentResult(agent.name, agent.provider, agent.role, True, text=text, latency_ms=int((time.perf_counter() - t0) * 1000))
        except Exception as exc:
            return AgentResult(agent.name, agent.provider, agent.role, False, error=str(exc), latency_ms=int((time.perf_counter() - t0) * 1000))

    with ThreadPoolExecutor(max_workers=len(selected), thread_name_prefix="jarvis-hive") as pool:
        futures = {pool.submit(worker, agent): agent for agent in selected}
        for future in as_completed(futures):
            with lock:
                result.results.append(future.result())

    result.results.sort(key=lambda item: item.name)
    successes = result.successful
    if synthesize and len(successes) >= 2:
        synthesizer = next((agent for agent in selected if agent.role == "lead" and any(r.name == agent.name and r.ok for r in successes)), None)
        if synthesizer is None:
            synthesizer = next((agent for agent in selected if agent.provider == "gemini"), None)
        if synthesizer:
            try:
                result.synthesis = _invoke(synthesizer, _synthesis_prompt(goal, successes), timeout)
            except Exception:
                result.synthesis = ""

    _ = started
    return result


def summarize(result: HiveResult) -> str:
    if not result.results:
        return "Hive mind unavailable."
    good = len(result.successful)
    total = len(result.results)
    lines = [f"Hive mind: {good}/{total} agents responded successfully."]
    for item in result.results:
        if item.ok:
            lines.append(f"- {item.name} ({item.provider}/{item.role}): {item.latency_ms} ms")
        else:
            lines.append(f"- {item.name} ({item.provider}/{item.role}): failed — {item.error}")
    if result.synthesis:
        lines.append("\nSynthesis:\n" + result.synthesis)
    elif result.successful:
        lines.append("\nBest available reports:\n" + "\n\n".join(item.text for item in result.successful[:3]))
    return "\n".join(lines)
