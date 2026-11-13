"""Score memdiag on the Goal 1 suite: recall, exact-turn accuracy and false positives, with Wilson intervals."""
from __future__ import annotations

import math
from collections import defaultdict

from memdiag import Event, run


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def case_events(case: dict) -> list[Event]:
    return [Event.from_dict(r, i) for i, r in enumerate(case["events"])]


def score_case(case: dict, judge=None) -> dict:
    res = run(case_events(case), judge=judge)
    found = [f for f in res["findings"] if f["type"] == case["type"]]
    out = {"case_id": case["case_id"], "type": case["type"], "split": case["split"], "attr": case["attr"],
           "control": case["control"], "found_turns": sorted({f["failing_turn"] for f in found})}
    if case["control"]:
        out["false_positive"] = bool(found)
    else:
        out["detected"] = bool(found)
        out["exact_turn"] = case["gold_turn"] in out["found_turns"]
    return out


def _rate(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": (k / n) if n else None, "ci95": [round(lo, 3), round(hi, 3)]}


def aggregate(rows: list[dict]) -> dict:
    """Per (split, type) and per (split, type, attr): recall, exact-turn accuracy and false-positive rate."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["split"], r["type"], "all")].append(r)
        groups[(r["split"], r["type"], r["attr"])].append(r)
        groups[(r["split"], "ALL", "all")].append(r)
    out = {}
    for (split, typ, attr), rs in sorted(groups.items()):
        pos = [r for r in rs if not r["control"]]
        ctl = [r for r in rs if r["control"]]
        out[f"{split}|{typ}|{attr}"] = {
            "recall": _rate(sum(r["detected"] for r in pos), len(pos)),
            "exact_turn": _rate(sum(r["exact_turn"] for r in pos), len(pos)),
            "false_positive": _rate(sum(r["false_positive"] for r in ctl), len(ctl)),
        }
    return out
