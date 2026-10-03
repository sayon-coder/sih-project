"""Agentic multi-source orchestration (Stage 2 of the staged build).

Three layers with one contract:

* :mod:`app.agents.planner` - an ordered plan of tool steps (LLM when
  available, deterministic rule-based fallback otherwise);
* :mod:`app.agents.tools` - the tool registry: genuinely working, read-only
  capabilities that wrap retrieval, the knowledge graph and the analysis
  layer;
* :mod:`app.agents.orchestrator` - the plan -> execute -> observe -> decide
  loop with a step budget, per-tool error isolation, abstention, validated
  citations and a persisted trace.

Import the heavy layers explicitly when you need them::

    from app.agents.orchestrator import run_agent
    from app.agents.tools import TOOL_REGISTRY, tool_catalog

Importing this package registers the ``agent_runs`` table with
``Base.metadata`` (via :mod:`app.agents.orchestrator`).
"""
from __future__ import annotations

from app.agents.orchestrator import (
    DISCLAIMER,
    AgentResult,
    AgentRun,
    AgentTrace,
    derive_confidence,
    run_agent,
)
from app.agents.planner import Plan, PlanStep, deterministic_plan, plan
from app.agents.tools import TOOL_REGISTRY, ToolSpec, execute_tool, tool_catalog

__all__ = [
    "DISCLAIMER",
    "AgentResult",
    "AgentRun",
    "AgentTrace",
    "TOOL_REGISTRY",
    "ToolSpec",
    "Plan",
    "PlanStep",
    "derive_confidence",
    "deterministic_plan",
    "execute_tool",
    "plan",
    "run_agent",
    "tool_catalog",
]
