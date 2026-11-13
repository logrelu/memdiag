"""The Goal 1 harness on tiny hand-written sessions: no dataset, no model."""
import json
import random

import pytest

from validation.goal1 import templates as T
from validation.goal1.mutate import BUILDERS, build_suite, to_events
from validation.goal1.score import aggregate, score_case, wilson


def _base(i):
    turns = []
    for j in range(4):
        turns += [["user", f"Question {i}.{j} about gardening tools and soil."],
                  ["assistant", f"Here is an answer {i}.{j} about gardening, with tips on soil and watering plans."]]
    return (f"sess_{i}", turns)


@pytest.mark.parametrize("typ", list(BUILDERS))
def test_builders_place_gold_on_the_injected_turn(typ):
    builder, n, attrs = BUILDERS[typ]
    rng = random.Random(1)
    for attr in attrs:
        (pos, gold, _), (ctl, none, _) = builder(rng, T.DEV, [_base(k) for k in range(n)], attr)
        assert none is None
        events = to_events("c", pos)
        assert events[gold]["role"] == "assistant"
        control_events = to_events("c", ctl)
        assert len(control_events) == len(events)
        # The control differs at the injected turn, or (a revoked instruction, a repair) at the user turn next to it.
        diffs = [i for i, (x, y) in enumerate(zip(events, control_events, strict=True)) if x["content"] != y["content"]]
        assert diffs and all(abs(i - gold) <= 1 for i in diffs)


def test_rules_mode_scores_dev_positives_and_controls():
    rng = random.Random(3)
    rows = []
    for typ, (builder, n, attrs) in BUILDERS.items():
        for attr in attrs:
            (pos, gold, _), (ctl, _, _) = builder(rng, T.DEV, [_base(k) for k in range(n)], attr)
            for sessions, g, control in ((pos, gold, False), (ctl, None, True)):
                case = {"case_id": f"{typ}-{attr}{'-ctl' if control else ''}", "type": typ, "split": "dev",
                        "attr": attr, "control": control, "gold_turn": g, "events": to_events("c", sessions)}
                rows.append(score_case(case))
    agg = aggregate(rows)
    assert agg["dev|ALL|all"]["false_positive"]["k"] == 0  # no control misfires on clean scaffolding
    assert agg["dev|CONSTRAINT_DROP|all"]["exact_turn"]["rate"] == 1.0
    assert agg["dev|STALE_FACT|city"]["exact_turn"]["rate"] == 1.0


def test_build_suite_is_deterministic(tmp_path):
    items = [{"question_id": f"q{i}", "haystack_session_ids": [f"s{i}_{k}" for k in range(4)],
              "haystack_dates": ["2023/01/01 (Sun) 10:00"] * 4,
              "haystack_sessions": [[{"role": r, "content": t} for r, t in _base(i * 10 + k)[1]] for k in range(4)]}
             for i in range(60)]
    path = tmp_path / "lme.json"
    path.write_text(json.dumps(items))
    import validation.goal1.mutate as m
    old = dict(m.COUNTS)
    m.COUNTS.update({"dev": 2, "heldout": 1})
    try:
        a, b = build_suite(path, seed=5), build_suite(path, seed=5)
    finally:
        m.COUNTS.clear()
        m.COUNTS.update(old)
    assert a == b and len(a) == 4 * 3 * 2
    assert all((c["gold_turn"] is None) == c["control"] for c in a)
    assert {c["split"] for c in a} == {"dev", "heldout"}


def test_wilson():
    lo, hi = wilson(17, 20)
    assert 0.6 < lo < 0.7 and 0.94 < hi < 0.96
    assert wilson(0, 0) == (0.0, 0.0)
