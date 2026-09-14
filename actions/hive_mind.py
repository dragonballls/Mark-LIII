from __future__ import annotations

from typing import Any

from core.hive_mind import run_hive, summarize


def hive_mind(parameters: dict, player=None, speak=None, **_: Any) -> str:
    """Fan a goal out to several configured hosted AI agents and synthesize their reports."""
    goal = str(parameters.get("goal", "")).strip()
    if not goal:
        return "Hive mind requires a goal."

    try:
        max_agents = int(parameters.get("max_agents", 6))
    except (TypeError, ValueError):
        max_agents = 6
    synthesize = bool(parameters.get("synthesize", True))
    result = run_hive(goal, max_agents=max_agents, synthesize=synthesize)
    text = summarize(result)

    if player:
        try:
            player.write_log("[Hive Mind] " + text.replace("\n", " | "))
        except Exception:
            pass
    if speak:
        try:
            good = len(result.successful)
            total = len(result.results)
            speak(f"Hive analysis complete. {good} of {total} intelligence nodes responded.")
        except Exception:
            pass
    return text


def hive_mind_status(parameters: dict, player=None, speak=None, **_: Any) -> str:
    """Report configured hive members without exposing credentials."""
    from core.hive_mind import load_agent_specs

    specs = load_agent_specs()
    if not specs:
        return "Hive mind has no configured AI agents."
    lines = [f"Hive mind has {len(specs)} configured agent(s):"]
    for spec in specs:
        project = f" project={spec.project}" if spec.project else ""
        lines.append(f"- {spec.name}: {spec.provider}/{spec.model}, role={spec.role}{project}")
    return "\n".join(lines)


TOOL = {
    "name": "hive_mind",
    "description": (
        "Use the isolated JARVIS hive mind to ask several explicitly configured hosted AI agents "
        "for independent analysis in parallel, then optionally synthesize their reports. Supports "
        "Gemini, Anthropic, and OpenAI-compatible endpoints. It never installs local LLMs, reads "
        "browser credentials, or performs external actions on its own."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "goal": {"type": "STRING", "description": "The problem or question for the hive to analyze."},
            "max_agents": {"type": "INTEGER", "description": "Maximum number of configured agents to query (default 6)."},
            "synthesize": {"type": "BOOLEAN", "description": "Whether to ask a configured lead agent to synthesize the reports."},
        },
        "required": ["goal"],
    },
    "handler": hive_mind,
}

HIVE_STATUS_TOOL = {
    "name": "hive_mind_status",
    "description": "Show which hosted AI agents are configured for the JARVIS hive without exposing API keys.",
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": hive_mind_status,
}
