"""memdiag: memory diagnostics for AI agents.

Reads an agent's conversation logs, separates memory failures from retrieval
failures, and replays user history through candidate memory strategies.
"""
from __future__ import annotations

import json

from .detect import diagnose
from .extract import RuleExtractor
from .metrics import Metric, check_thresholds, compute_metrics
from .schema import CATEGORIES, Event, Finding
from .strategies import compare

__version__ = "0.1.0"
__all__ = ["CATEGORIES", "Event", "Finding", "Metric", "RuleExtractor", "check_thresholds", "compute_metrics",
           "load_events", "load_jsonl", "run", "run_files"]


def load_jsonl(path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def load_events(path) -> list[Event]:
    return [Event.from_dict(d, i) for i, d in enumerate(load_jsonl(path))]


def run(events: list[Event], docs=None) -> dict:
    """Full diagnosis: findings, summary, strategy comparison, timeline."""
    ex = RuleExtractor()
    findings, tl, stats = diagnose(events, docs, ex)
    strategies, probes = compare(events, tl, ex)

    by_cat, by_class = {}, {}
    for f in findings:
        by_cat[f.category] = by_cat.get(f.category, 0) + 1
        by_class[f.failure_class] = by_class.get(f.failure_class, 0) + 1

    primary = [f for f in findings if f.category != "context_overload"]
    mem = sum(1 for f in primary if f.failure_class == "memory")
    ret = sum(1 for f in primary if f.failure_class == "retrieval")
    best = max(strategies, key=lambda r: (r["accuracy"], -r["avg_tokens"])) if strategies else None
    baseline = next((r for r in strategies if r["strategy"] == "Full history in context"), None)

    findings_d = [f.to_dict() for f in findings]
    metrics = compute_metrics(findings_d, stats["opportunities"])
    return {
        "stats": stats,
        "metrics": {k: m.to_dict() for k, m in metrics.items()},
        "summary": {
            "findings": len(primary),
            "memory_failures": mem,
            "retrieval_failures": ret,
            "memory_share": mem / len(primary) if primary else 0.0,
            "by_category": by_cat,
            "by_class": by_class,
            "best_strategy": best,
            "full_history_baseline": baseline,
        },
        "findings": findings_d,
        "strategies": strategies,
        "probes": len(probes),
        "timeline": tl.to_rows(),
    }


def run_files(traces: str, docs: str | None = None) -> dict:
    return run(load_events(traces), load_jsonl(docs) if docs else None)
