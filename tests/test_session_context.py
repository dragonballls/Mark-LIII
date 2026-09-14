from core.session_context import build_replay_prompt


# Full-suite validation trigger for the reconnect-context fix.
def test_replay_prompt_is_bounded_and_preserves_order():
    turns = [f"User: turn {i}" for i in range(20)]
    prompt = build_replay_prompt(turns)
    assert "User: turn 8" in prompt
    assert "User: turn 19" in prompt
    assert prompt.index("User: turn 8") < prompt.index("User: turn 19")


def test_empty_replay_is_empty():
    assert build_replay_prompt([]) == ""


def test_replay_has_a_hard_character_bound():
    turns = ["x" * 1000 for _ in range(12)]
    prompt = build_replay_prompt(turns)
    assert len(prompt) <= 7000
