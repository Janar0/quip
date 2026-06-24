"""Regression test: multi-round usage must be summed, not overwritten.

The orchestrator emits one `usage` event per round (tool/search turns run
multiple rounds). The chat path used to keep only the last round's usage
(`last_usage = data`), so cost/tokens for every earlier round were dropped —
costs came out roughly halved for tool-using turns.
"""
from quip.services.completion.service import _accumulate_usage


def test_accumulate_sums_tokens_and_cost_across_rounds():
    acc = None
    rounds = [
        {"prompt_tokens": 1000, "completion_tokens": 200, "cached_tokens": 0,
         "cost": 0.01, "provider": "openai", "generation_id": "gen-1"},
        {"prompt_tokens": 1500, "completion_tokens": 300, "cached_tokens": 100,
         "cost": 0.02, "provider": "openai", "generation_id": "gen-2"},
    ]
    for r in rounds:
        acc = _accumulate_usage(acc, r)

    assert acc["prompt_tokens"] == 2500
    assert acc["completion_tokens"] == 500
    assert acc["cached_tokens"] == 100
    assert abs(acc["cost"] - 0.03) < 1e-9
    # generation_id keeps the most recent round (used as cost-fetch fallback).
    assert acc["generation_id"] == "gen-2"
    assert acc["provider"] == "openai"


def test_accumulate_handles_none_and_missing_fields():
    assert _accumulate_usage(None, None) is None
    acc = _accumulate_usage(None, {"prompt_tokens": 10})
    assert acc["prompt_tokens"] == 10
    assert acc["completion_tokens"] == 0
    assert acc["cost"] == 0.0
    # A later event with no cost must not wipe the running total.
    acc = _accumulate_usage(acc, {"cost": 0.05})
    assert abs(acc["cost"] - 0.05) < 1e-9
    assert acc["prompt_tokens"] == 10
