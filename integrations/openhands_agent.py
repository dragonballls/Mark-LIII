from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class OpenHandsUnavailable(RuntimeError):
    """Raised when the optional OpenHands coding engine cannot be initialized."""


def _load() -> tuple[Any, Any, Any, Any, Any]:
    """Load the current OpenHands SDK surface lazily."""
    try:
        from pydantic import SecretStr
        from openhands.sdk import Agent, Conversation, LLM, Tool
        from openhands.tools.file_editor import FileEditorTool
        from openhands.tools.task_tracker import TaskTrackerTool
        from openhands.tools.terminal import TerminalTool
    except Exception as exc:  # pragma: no cover - depends on optional install
        raise OpenHandsUnavailable(str(exc)) from exc
    return Agent, Conversation, LLM, Tool, (FileEditorTool, TaskTrackerTool, TerminalTool, SecretStr)


def available() -> bool:
    """Return whether the optional OpenHands SDK can be imported."""
    try:
        _load()
        return True
    except OpenHandsUnavailable:
        return False


def _credentials() -> tuple[str, str, str | None]:
    """Prefer the zero-priced OpenRouter free router when configured."""
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if openrouter_key:
        return (
            openrouter_key,
            os.getenv("JARVIS_OPENHANDS_MODEL") or os.getenv("OPENHANDS_MODEL") or "openrouter/free",
            os.getenv("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1",
        )

    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("JARVIS_OPENHANDS_API_KEY")
    if api_key:
        return (
            api_key,
            os.getenv("JARVIS_OPENHANDS_MODEL") or os.getenv("OPENHANDS_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5.5",
            os.getenv("JARVIS_OPENHANDS_BASE_URL") or os.getenv("OPENAI_BASE_URL") or None,
        )

    raise OpenHandsUnavailable(
        "No OpenHands-compatible API key is configured. Configure OPENROUTER_API_KEY "
        "for OpenRouter's zero-priced free router, or an OpenAI-compatible key."
    )


def run(workspace: Path, goal: str, max_iterations: int = 50) -> list[dict[str, Any]]:
    """Run a bounded OpenHands coding conversation in an explicit workspace."""
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise OpenHandsUnavailable(f"Workspace does not exist: {workspace}")

    Agent, Conversation, LLM, Tool, tool_types = _load()
    api_key, model, base_url = _credentials()
    terminal_cls, editor_cls, tracker_cls, SecretStr = tool_types

    llm_kwargs: dict[str, Any] = {
        "model": model,
        "api_key": SecretStr(api_key),
    }
    if base_url:
        llm_kwargs["base_url"] = base_url

    llm = LLM(**llm_kwargs)
    agent = Agent(
        llm=llm,
        tools=[
            Tool(name=terminal_cls.name),
            Tool(name=editor_cls.name),
            Tool(name=tracker_cls.name),
        ],
    )
    conversation = Conversation(
        agent=agent,
        workspace=workspace,
        max_iteration_per_run=max(1, min(int(max_iterations), 100)),
        delete_on_close=False,
        visualizer=None,
    )
    conversation.send_message(goal)
    conversation.run()

    return [
        {"event": "coding_started", "engine": "openhands", "workspace": str(workspace), "model": model},
        {"event": "coding_completed", "engine": "openhands", "workspace": str(workspace), "model": model},
    ]
