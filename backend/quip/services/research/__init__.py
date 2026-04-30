# backend/quip/services/research/__init__.py
"""Deep Research orchestrator — multi-agent research with sub-agents."""
from quip.services.research.orchestrator import run_deep_research
from quip.services.research.types import ResearchEvent

__all__ = ["run_deep_research", "ResearchEvent"]
