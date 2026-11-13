"""Normalized memory metrics: each score is in [0, 1], higher is better.

A score is 1 - failures / opportunities, where the opportunity count is reported with the score.
A metric with zero opportunities has score None (not applicable). It is never reported as 1.0,
because "the agent never had the chance to fail" is not evidence of good memory.

Definitions live in docs/metrics.md; keep both in sync.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Optional

MEMORY_CATEGORIES = ("stale_memory", "failed_deletion", "cross_user_leak", "hallucinated_memory")


@dataclass(frozen=True)
class Metric:
    name: str
    description: str
    score: Optional[float]
    failures: int
    opportunities: int

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description, "score": self.score,
                "failures": self.failures, "opportunities": self.opportunities}


def _metric(name: str, description: str, failures: int, opportunities: int) -> Metric:
    score = None if opportunities == 0 else max(0.0, 1 - failures / opportunities)
    return Metric(name, description, score, failures, opportunities)


def _key(attribute: str) -> str:
    from .ledger import normalize_key
    return attribute if "." in attribute else normalize_key("user", attribute)


def compute_metrics(findings: list[dict], opportunities: dict) -> dict[str, Metric]:
    """Score an agent from findings (as dicts, see Finding.to_dict) and opportunity counts."""
    count = {}
    for f in findings:
        count[f["category"]] = count.get(f["category"], 0) + 1
    # A fact the user asked to forget counts once, however many times the agent repeated it.
    leaked = len({(f["user_id"], f["attribute"]) for f in findings if f["category"] == "failed_deletion"})
    asserted = opportunities.get("fact_assertions", 0)
    # Assertion-based metrics count only findings on rule-read assertions; ledger-only stale findings
    # (a mention, not an assertion) count in fact_currency instead. Findings without a detector are legacy.
    on_assertions = Counter(f["category"] for f in findings if f.get("detector", "rules.").startswith("rules."))
    # fact_currency: one failure per (turn, fact), matching its per-(turn, fact) denominator.
    stale_pairs = len({(f.get("failing_turn", f["ts"]), _key(f["attribute"]))
                       for f in findings if f["category"] == "stale_memory"})
    currency_opp = opportunities.get("updated_key_mentions", opportunities.get("update_assertions", 0))
    # A turn that re-asks for several known facts is one failure, matching the per-turn denominator.
    reask_turns = len({(f["user_id"], f.get("failing_turn", f["ts"])) for f in findings
                       if f["category"] == "forgotten_memory"})

    metrics = [
        _metric("memory_faithfulness",
                "Share of user facts the agent asserted that were correct and current",
                sum(on_assertions.get(c, 0) for c in MEMORY_CATEGORIES), asserted),
        _metric("fact_currency",
                "Share of replies mentioning a fact the user had updated that used the latest value",
                stale_pairs, currency_opp),
        _metric("deletion_compliance",
                "Share of 'forget this' requests the agent never later violated",
                leaked, opportunities.get("deletion_requests", 0)),
        _metric("user_isolation",
                "Share of assertions that did not use another user's value",
                count.get("cross_user_leak", 0), opportunities.get("shared_attr_assertions", 0)),
        _metric("groundedness",
                "Share of assertions the user actually stated (not invented)",
                count.get("hallucinated_memory", 0), asserted),
        _metric("recall_continuity",
                "Share of turns, after the user gave a fact, where the agent did not re-ask for it",
                reask_turns, opportunities.get("known_fact_turns", 0)),
        _metric("constraint_retention",
                "Share of checks where a reply kept an instruction the user gave earlier in the session",
                count.get("constraint_drop", 0), opportunities.get("constraint_turn_pairs", 0)),
    ]
    return {m.name: m for m in metrics}


def check_thresholds(metrics: dict[str, Metric], thresholds: dict[str, float]) -> list[str]:
    """Return a message per violated threshold. An unscored (None) metric never fails a gate."""
    problems = []
    for name, minimum in thresholds.items():
        if name not in metrics:
            problems.append(f"unknown metric '{name}' (choose from: {', '.join(metrics)})")
            continue
        m = metrics[name]
        if m.score is not None and m.score < minimum:
            problems.append(f"{name} = {m.score:.2f} is below {minimum:.2f} "
                            f"({m.failures} failures / {m.opportunities} opportunities)")
    return problems
