"""Validated bounds for one Deep Research execution.

Round/search limits can be set with the matching RESEARCH_MAX_* environment or
stored settings keys. The cost threshold uses provider-reported cost: one call
admitted below it may cross it, and providers without cost reporting are not
covered by a hard spend guarantee.
"""

import math
from dataclasses import dataclass

from quip.core.config import get_setting


def _integer_setting(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(get_setting(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if minimum <= value <= maximum else default


def _cost_setting(name: str, default: float) -> float:
    try:
        value = float(get_setting(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and 0 <= value <= 100 else default


@dataclass(frozen=True)
class ResearchLimits:
    max_child_agents: int = 8
    max_concurrent_agents: int = 3
    max_concurrent_runs: int = 2
    max_runtime_seconds: int = 600
    max_cost_usd: float = 1.0
    max_orchestrator_rounds: int = 20
    max_subagent_rounds: int = 15
    max_web_searches: int = 100

    @classmethod
    def from_config(cls) -> "ResearchLimits":
        max_children = _integer_setting("research_max_child_agents", 8, 1, 32)
        max_agents = _integer_setting("research_max_concurrent_agents", 3, 1, 8)
        return cls(
            max_child_agents=max_children,
            max_concurrent_agents=min(max_agents, max_children),
            max_concurrent_runs=_integer_setting("research_max_concurrent_runs", 2, 1, 8),
            max_runtime_seconds=_integer_setting("research_max_runtime_seconds", 600, 10, 3600),
            max_cost_usd=_cost_setting("research_max_cost_usd", 1.0),
            max_orchestrator_rounds=_integer_setting("research_max_orchestrator_rounds", 20, 1, 40),
            max_subagent_rounds=_integer_setting("research_max_subagent_rounds", 15, 1, 30),
            max_web_searches=_integer_setting("research_max_web_searches", 100, 1, 500),
        )
