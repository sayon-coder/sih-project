"""Planning layer: which tools to run, in which order.

Two planners with one contract (:class:`Plan`):

* **LLM planner** - asks the configured model for a JSON plan and validates it
  against the registry. The model can only *choose* tools and phrase reasons;
  it cannot invent a tool, run without a required product version, or exceed
  the step budget.
* **Deterministic fallback** (:func:`deterministic_plan`) - keyword rules with
  a fixed priority order. Used whenever the model is unavailable, the response
  is not valid JSON, every proposed step is rejected, or ``llm=False`` was
  passed to :func:`app.agents.orchestrator.run_agent`.

The fallback is exported and unit-tested on its own, so planning quality never
depends on a live model in CI.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.agents.tools import TOOL_REGISTRY

logger = logging.getLogger(__name__)

#: Hard ceiling on plan length (the orchestrator enforces it again at runtime).
MAX_PLAN_STEPS = 5

PLAN_SYSTEM_PROMPT = (
    "You are the planning step of a preliminary IP/biodiversity decision-support "
    "agent. You only decide WHICH tools to run and with which arguments; you never "
    "answer the question yourself and you never state that anything is eligible, "
    "approved, patentable, safe or compliant.\n"
    "Available tools:\n"
    "{tool_catalog}\n"
    "Respond with ONE JSON object and nothing else:\n"
    '{{"rationale": "<short>", "steps": [{{"tool": "<name>", "args": {{...}}, '
    '"reason": "<why this step>"}}]}}\n'
    "Rules: at most {max_steps} steps; start with retrieve_corpus; a tool whose "
    "parameters require product_version_id may only be used when that id is "
    "provided in the user message; unknown tools are rejected."
)


# ============================================================
# Plan structure
# ============================================================

@dataclass
class PlanStep:
    """One tool invocation the orchestrator should attempt."""

    tool: str
    args: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"tool": self.tool, "args": dict(self.args), "reason": self.reason}


@dataclass
class Plan:
    """An ordered tool plan plus how it was produced."""

    steps: List[PlanStep] = field(default_factory=list)
    rationale: str = ""
    #: ``"llm"`` or ``"fallback"`` (also ``"fallback"`` when the LLM plan was rejected).
    source: str = "fallback"
    rejected: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "rationale": self.rationale,
            "rejected": list(self.rejected),
            "steps": [step.to_dict() for step in self.steps],
        }


# ============================================================
# Validation (shared by both planners)
# ============================================================

def validate_steps(
    raw_steps: Any,
    *,
    product_version_id: Optional[int],
    max_steps: int,
) -> tuple[List[PlanStep], List[str]]:
    """Turn untrusted step proposals into runnable, budgeted steps.

    Rejects (and reports) unknown tools, malformed entries, version-scoped tools
    without a selected version, and duplicates. Never raises.
    """
    steps: List[PlanStep] = []
    rejected: List[str] = []
    seen = set()

    if not isinstance(raw_steps, list):
        return [], ["steps was not a list"]

    for item in raw_steps:
        if not isinstance(item, dict):
            rejected.append("non-object step")
            continue
        tool = str(item.get("tool") or item.get("name") or "").strip()
        spec = TOOL_REGISTRY.get(tool)
        if spec is None:
            rejected.append(f"unknown tool '{tool}'" if tool else "step without a tool")
            continue
        raw_args = item.get("args")
        args: Dict[str, Any] = dict(raw_args) if isinstance(raw_args, dict) else {}
        if spec.requires_version and not product_version_id:
            rejected.append(f"{tool} requires a selected product version")
            continue
        key = (tool, json.dumps(args, sort_keys=True, default=str))
        if key in seen:
            rejected.append(f"duplicate {tool}")
            continue
        seen.add(key)
        steps.append(PlanStep(tool=tool, args=args, reason=str(item.get("reason") or "")))
        if len(steps) >= max(1, max_steps):
            break

    return steps, rejected


# ============================================================
# Deterministic fallback planner
# ============================================================

def _has(text: str, terms: List[str]) -> bool:
    return any(re.search(rf"\b{re.escape(term)}", text) for term in terms)


def _detect_jurisdiction(text: str) -> Optional[str]:
    if re.search(r"\bindia\b|\bindian\b", text):
        return "India"
    if re.search(r"\binternational\b|\bglobal\b|\btrips\b|\bwipo\b|\bnagoya\b", text):
        return "International"
    return None


# Term lists are literal prefixes matched on word boundaries (see _has).
GRAPH_TERMS = [
    "graph", "relation", "related", "path", "connect", "section", "act", "statute",
    "barred", "bar", "governs", "route", "reasoning", "link", "patent", "trademark",
    "copyright", "design", "geographical", "trade secret", "plant variet",
    "traditional knowledge", "knowledge graph",
]
ABS_TERMS = [
    "biodiversity", "benefit", "abs", "wild", "nagoya", "biological", "origin",
    "access and", "harvest",
]
CLASSIFY_TERMS = [
    "classif", "categor", "which type", "formulation type", "what kind", "category",
]
SOURCE_TERMS = [
    "official source", "source", "where to", "registry", "authority", "guidance",
    "which act", "which statute", "ministry", "consult",
]

#: Fixed priority - the fallback emits steps in this order until the budget runs out.
FALLBACK_PRIORITY = [
    "retrieve_corpus",
    "query_knowledge_graph",
    "ip_route_map",
    "classify_formulation",
    "biodiversity_screen",
    "official_sources_for",
]


def deterministic_plan(
    query: str,
    *,
    product_version_id: Optional[int] = None,
    max_steps: int = MAX_PLAN_STEPS,
) -> Plan:
    """Rule-based plan: no model, no network, fully reproducible.

    Always starts from the corpus, adds the knowledge graph when the question
    is about instruments/routes/relations, and adds the product-scoped tools
    only when a Product Passport version is selected.
    """
    text = (query or "").lower()
    max_steps = max(1, int(max_steps))

    proposals: List[PlanStep] = [
        PlanStep("retrieve_corpus", {"query": query}, "Ground the answer in the verified corpus.")
    ]

    if _has(text, GRAPH_TERMS):
        proposals.append(
            PlanStep(
                "query_knowledge_graph",
                {"query": query},
                "Look up the relational chain for the concepts mentioned.",
            )
        )

    if product_version_id:
        proposals.append(
            PlanStep(
                "ip_route_map",
                {},
                "Use the selected Product Passport's deterministic route map.",
            )
        )
        if _has(text, CLASSIFY_TERMS):
            proposals.append(
                PlanStep(
                    "classify_formulation",
                    {},
                    "The question asks for the formulation category.",
                )
            )
        if _has(text, ABS_TERMS):
            proposals.append(
                PlanStep(
                    "biodiversity_screen",
                    {},
                    "The question touches biological resources / benefit sharing.",
                )
            )

    if _has(text, SOURCE_TERMS):
        jurisdiction = _detect_jurisdiction(text)
        args: Dict[str, Any] = {}
        if jurisdiction:
            args["jurisdiction"] = jurisdiction
        proposals.append(
            PlanStep("official_sources_for", args, "Name the official instruments/registries.")
        )

    # Priority order, budgeted.
    ordered: List[PlanStep] = []
    for name in FALLBACK_PRIORITY:
        if len(ordered) >= max_steps:
            break
        for step in proposals:
            if step.tool == name:
                ordered.append(step)
                break

    rationale = (
        "Deterministic rule-based plan (no model used): corpus first, then the "
        "knowledge graph and product-scoped tools where the question calls for them."
    )
    return Plan(steps=ordered, rationale=rationale, source="fallback")


# ============================================================
# LLM planner
# ============================================================

def _parse_json(raw: str) -> Dict[str, Any]:
    """Parse the model's response, tolerating code fences and stray prose."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        text = text[start : end + 1]
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("plan JSON must be an object")
    return parsed


def plan(
    query: str,
    *,
    product_version_id: Optional[int] = None,
    max_steps: int = MAX_PLAN_STEPS,
    llm: Any = None,
) -> Plan:
    """Produce a validated plan for ``query``.

    ``llm`` is a provider exposing ``generate(system_prompt, user_prompt)``.
    ``None`` means "no model requested/available" and goes straight to the
    deterministic planner; any model failure degrades to the fallback rather
    than aborting the run.
    """
    max_steps = max(1, min(int(max_steps), MAX_PLAN_STEPS))

    if llm is None:
        return deterministic_plan(query, product_version_id=product_version_id, max_steps=max_steps)

    try:
        catalog = json.dumps(
            [
                {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.contract(),
                }
                for spec in TOOL_REGISTRY.values()
            ],
            ensure_ascii=False,
        )
        user_prompt = (
            f"Question: {query}\n"
            f"product_version_id: {product_version_id if product_version_id else 'none (product tools unavailable)'}\n"
            f"max_steps: {max_steps}"
        )
        raw = llm.generate(
            system_prompt=PLAN_SYSTEM_PROMPT.format(
                tool_catalog=catalog, max_steps=max_steps
            ),
            user_prompt=user_prompt,
        )
        parsed = _parse_json(raw)
    except Exception as exc:
        logger.warning("LLM planning failed (%s); using deterministic fallback", exc)
        fallback = deterministic_plan(
            query, product_version_id=product_version_id, max_steps=max_steps
        )
        fallback.rationale = f"Deterministic fallback after planner error: {exc}"
        return fallback

    steps, rejected = validate_steps(
        parsed.get("steps"),
        product_version_id=product_version_id,
        max_steps=max_steps,
    )

    if not steps:
        fallback = deterministic_plan(
            query, product_version_id=product_version_id, max_steps=max_steps
        )
        fallback.rationale = (
            "Deterministic fallback: the model produced no usable steps "
            f"({'; '.join(rejected) if rejected else 'empty plan'})."
        )
        fallback.rejected = rejected
        return fallback

    return Plan(
        steps=steps,
        rationale=str(parsed.get("rationale") or ""),
        source="llm",
        rejected=rejected,
    )
