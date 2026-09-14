from __future__ import annotations

from typing import Any

from core.hive_mind import health_snapshot, load_agent_specs


def hive_mind_status(parameters: dict, player=None, speak=None, **_: Any) -> str:
    """Report configured hive members and credential-free runtime health."""
    specs = load_agent_specs()
    if not specs:
        return "Hive mind has no configured AI agents."

    health = health_snapshot()
    lines = [f"Hive mind has {len(specs)} configured agent(s):"]
    for spec in specs:
        project = f" project={spec.project}" if spec.project else ""
        state = health.get(spec.name, {})
        if state:
            status = "healthy" if state.get("ok") else "degraded"
            failures = int(state.get("consecutive_failures", 0))
            latency = int(state.get("last_latency_ms", 0))
            lines.append(
                f"- {spec.name}: {spec.provider}/{spec.model}, role={spec.role}{project}; "
                f"status={status}, failures={failures}, last_latency={latency}ms"
            )
        else:
            lines.append(f"- {spec.name}: {spec.provider}/{spec.model}, role={spec.role}{project}; status=unprobed")
    return "\n".join(lines)


TOOL = {
    "name": "hive_mind_status",
    "description": "Show configured hosted AI agents and credential-free runtime health for the JARVIS hive.",
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": hive_mind_status,
}
