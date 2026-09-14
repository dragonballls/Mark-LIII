from __future__ import annotations

from typing import Any

from core.hive_mind import load_agent_specs


def hive_mind_status(parameters: dict, player=None, speak=None, **_: Any) -> str:
    """Report configured hive members without exposing credentials."""
    specs = load_agent_specs()
    if not specs:
        return "Hive mind has no configured AI agents."
    lines = [f"Hive mind has {len(specs)} configured agent(s):"]
    for spec in specs:
        project = f" project={spec.project}" if spec.project else ""
        lines.append(f"- {spec.name}: {spec.provider}/{spec.model}, role={spec.role}{project}")
    return "\n".join(lines)


TOOL = {
    "name": "hive_mind_status",
    "description": "Show configured hosted AI agents for the JARVIS hive without exposing API keys.",
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": hive_mind_status,
}
