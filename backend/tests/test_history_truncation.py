"""Regression tests for history truncation and model validation.

ce109bc introduced _validate_model / _truncate_history. A cache miss made
_validate_model default context_length to 4096, and _truncate_history then
dropped the latest user message — the model received only the system prompt.
"""
from quip.services.completion.service import _truncate_history, _validate_model


def _big_system_prompt() -> str:
    # Realistic system prompt with tool gating + skills index easily exceeds 4 KB.
    return "You are a helpful assistant. " * 400


def test_uncached_model_does_not_truncate_to_tiny_context():
    """A model missing from the cache must not be treated as a 4096-token model."""
    info = _validate_model("anthropic/claude-sonnet-4")
    # Unknown context must mean "don't truncate", not "assume 4096".
    assert info.get("context_length", 0) <= 0


def test_latest_user_message_is_never_dropped():
    """Truncation must always preserve the system prompt and the latest user turn."""
    history = [
        {"role": "system", "content": _big_system_prompt()},
        {"role": "user", "content": "What is the capital of France?"},
    ]
    # Even with a genuinely tiny context window, the question must survive.
    out = _truncate_history(history, {"context_length": 4096})
    assert any(m["role"] == "user" for m in out), "latest user message was dropped"
    assert out[-1]["content"] == "What is the capital of France?"


def test_oldest_turns_still_trimmed_when_over_budget():
    """Old turns should still be dropped, but never the final user message."""
    history = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "x" * 20000},      # old, huge
        {"role": "assistant", "content": "y" * 20000},  # old, huge
        {"role": "user", "content": "latest question"},
    ]
    out = _truncate_history(history, {"context_length": 4096})
    roles = [m["role"] for m in out]
    assert "system" in roles
    assert out[-1]["content"] == "latest question"
    # The huge old turns should have been trimmed.
    assert len(out) < len(history)
