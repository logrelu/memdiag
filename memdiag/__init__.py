"""memdiag: memory diagnostics for AI agents.

Reads an agent's conversation logs, separates memory failures from retrieval
failures, and replays user history through candidate memory strategies.
"""
from __future__ import annotations

import json
from dataclasses import replace

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


def _merge(legacy: list[Finding], extra: list[Finding]) -> list[Finding]:
    """Legacy rule findings plus ledger findings, minus duplicates (same turn, type and fact key)."""
    from .ledger import normalize_key

    def ident(f: Finding):
        key = f.attribute if "." in f.attribute else normalize_key("user", f.attribute)
        return f.failing_turn, f.type, key

    seen = {ident(f) for f in legacy}
    merged = legacy + [f for f in extra if ident(f) not in seen]
    repaired = {f.failing_turn for f in merged if f.category == "user_repair"}
    for f in merged:  # the user had to repeat themselves: more confidence it was a memory failure
        if f.failing_turn in repaired and f.failure_class == "memory":
            f.confidence = min(1.0, f.confidence + 0.25)
    return sorted(merged, key=lambda f: (f.ts, f.failing_turn))


def run(events: list[Event], docs=None, judge=None) -> dict:
    """Full diagnosis: findings, summary, strategy comparison, timeline, ledger.

    With a judge (memdiag.judge), the ledger also uses the LLM extractor and the ledger detectors confirm
    candidates with one specific question each. Without one, everything is rule-based.
    """
    from .detectors import detect_with_ledger, locate
    from .ledger import build_ledger

    if len({e.index for e in events}) < len(events):
        events = [replace(e, index=i) for i, e in enumerate(events)]
    ex = RuleExtractor()
    findings, tl, stats = diagnose(events, docs, ex)
    ledger = build_ledger(events, judge=judge, extractor=ex)
    extra, ledger_opp = detect_with_ledger(events, ledger, judge)
    findings = _merge(findings, extra)
    by_index = {e.index: e for e in events}
    for f in findings:
        f.location = locate(f, by_index[f.failing_turn], ledger)
    stats["opportunities"]["updated_key_mentions"] = ledger_opp["updated_key_mentions"]
    if judge is not None:  # re-asks of any ledger fact can be checked, not only the rule attributes
        stats["opportunities"]["known_fact_turns"] = ledger_opp["live_fact_turns"]
    stats["failed_turns"] = len({f.failing_turn for f in findings if f.failure_class in ("memory", "retrieval")})
    strategies, probes = compare(events, tl, ex)

    by_cat, by_class = {}, {}
    for f in findings:
        by_cat[f.category] = by_cat.get(f.category, 0) + 1
        by_class[f.failure_class] = by_class.get(f.failure_class, 0) + 1

    primary = [f for f in findings if f.category != "context_overload" and f.failure_class != "signal"]
    mem = sum(1 for f in primary if f.failure_class == "memory")
    ret = sum(1 for f in primary if f.failure_class == "retrieval")
    best = max(strategies, key=lambda r: (r["accuracy"], -r["avg_tokens"])) if strategies else None
    baseline = next((r for r in strategies if r["strategy"] == "Full history in context"), None)

    findings_d = [f.to_dict() for f in findings]
    metrics = compute_metrics(findings_d, stats["opportunities"])
    return {
        "mode": "llm" if judge is not None else "rules",
        "judge_model": getattr(judge, "model", None),
        "judge_usage": dict(judge.usage.by_role) if judge is not None else {},
        "repair_count": sum(f.category == "user_repair" for f in findings),
        "ledger": ledger.to_rows(),
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


def run_files(traces: str, docs: str | None = None, fmt: str = "auto", judge=None) -> dict:
    """Diagnose a log file in any format memdiag.adapters reads (auto-detected by default)."""
    from .adapters import load
    return run(load(traces, fmt), load_jsonl(docs) if docs else None, judge=judge)
