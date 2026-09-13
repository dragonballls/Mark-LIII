from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class OpenHandsUnavailable(RuntimeError):
    pass


def _load() -> tuple[Any, Any, Any, Any]:
    try:
        from openhands.sdk import Agent, Conversation, LLM
        from openhands.tools import FileEditorTool, TaskTrackerTool, TerminalTool
    except Exception as exc:  # pragma: no cover
        raise OpenHandsUnavailable(str(exc)) from exc
    return Agent, Conversation, LLM, (FileEditorTool, TaskTrackerTool, TerminalTool)


def available() -> bool:
    try:
        _load()
        return True
    except OpenHandsUnavailable:
        return False


def run(workspace: Path, goal: str, max_iterations: int = 50) -> list[dict[str, Any]]:
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise OpenHandsUnavailable(f"Workspace does not exist: {workspace}")

    Agent, Conversation, LLM, tool_types = _load()
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("JARVIS_OPENHANDS_API_KEY")
    if not api_key:
        raise OpenHandsUnavailable("No OpenAI API key is configured for OpenHands.")

    model = (
        os.getenv("JARVIS_OPENHANDS_MODEL")
        or os.getenv("OPENHANDS_MODEL")
        or os.getenv("OPENAI_MODEL")
        or "gpt-5.5"
    )

    llm = LLM(model=model, api_key=api_key)
    agent = Agent(
        llm=llm,
        tools=[tool_type() for tool_type in tool_types],
    )
    conversation = Conversation(
        agent=agent,
        workspace=workspace,
        max_iteration_per_run=max_iterations,
        delete_on_close=False,
    )
    conversation.send_message(goal)
    conversation.run()

    return [
        {"event": "coding_started", "engine": "openhands", "workspace": str(workspace)},
        {"event": "coding_completed", "engine": "openhands", "workspace": str(workspace)},
    ]
