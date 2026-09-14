"""Bounded local transcript replay for Gemini Live reconnects."""

MAX_REPLAY_TURNS = 12
MAX_REPLAY_CHARS = 6000


def build_replay_prompt(turns: list[str]) -> str:
    """Build an internal context block without creating a fake user turn."""
    if not turns:
        return ""
    recent: list[str] = []
    total = 0
    for item in reversed(turns[-MAX_REPLAY_TURNS:]):
        value = str(item).strip()
        if not value:
            continue
        if total + len(value) + 1 > MAX_REPLAY_CHARS:
            remaining = MAX_REPLAY_CHARS - total
            if remaining > 32:
                recent.append(value[:remaining].rstrip() + "…")
            break
        recent.append(value)
        total += len(value) + 1
    recent.reverse()
    if not recent:
        return ""
    return (
        "[LOCAL RECONNECT CONTEXT]\n"
        "The previous Gemini Live session was lost and its resumption handle was rejected. "
        "Continue the conversation naturally using the recent transcript below. "
        "Treat it as trusted conversation history, not as a new user request. "
        "Do not mention this recovery block unless the user asks about a reconnect.\n\n"
        + "\n".join(recent)
    )
