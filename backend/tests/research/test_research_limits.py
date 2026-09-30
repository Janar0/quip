from quip.core.config import set_setting
from quip.services.research.limits import ResearchLimits


def test_research_limits_read_configured_bounded_values():
    set_setting("research_max_child_agents", "5")
    set_setting("research_max_concurrent_agents", "2")
    set_setting("research_max_concurrent_runs", "3")
    set_setting("research_max_runtime_seconds", "900")
    set_setting("research_max_cost_usd", "2.50")
    set_setting("research_max_orchestrator_rounds", "4")
    set_setting("research_max_subagent_rounds", "6")
    set_setting("research_max_web_searches", "40")

    limits = ResearchLimits.from_config()

    assert limits.max_child_agents == 5
    assert limits.max_concurrent_agents == 2
    assert limits.max_concurrent_runs == 3
    assert limits.max_runtime_seconds == 900
    assert limits.max_cost_usd == 2.5
    assert limits.max_orchestrator_rounds == 4
    assert limits.max_subagent_rounds == 6
    assert limits.max_web_searches == 40


def test_research_limits_reject_invalid_or_unbounded_values():
    set_setting("research_max_child_agents", "1000000")
    set_setting("research_max_concurrent_agents", "0")
    set_setting("research_max_concurrent_runs", "nan")
    set_setting("research_max_runtime_seconds", "-10")
    set_setting("research_max_cost_usd", "inf")
    set_setting("research_max_orchestrator_rounds", "1000000")
    set_setting("research_max_subagent_rounds", "0")
    set_setting("research_max_web_searches", "nan")

    limits = ResearchLimits.from_config()

    assert limits.max_child_agents == 8
    assert limits.max_concurrent_agents == 3
    assert limits.max_concurrent_runs == 2
    assert limits.max_runtime_seconds == 600
    assert limits.max_cost_usd == 1.0
    assert limits.max_orchestrator_rounds == 20
    assert limits.max_subagent_rounds == 15
    assert limits.max_web_searches == 100
