"""The Goal 1 harness on tiny hand-written sessions: no dataset, no model."""
import json
import random

import pytest

from validation.goal1 import templates as T
from validation.goal1.mutate import BUILDERS, build_suite, to_events
from validation.goal1.score import aggregate, base_id, score_case, wilson


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
        (pos, gold, _), (ctl, none, _), *_ = builder(rng, T.DEV, [_base(k) for k in range(n)], attr)
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
            (pos, gold, _), (ctl, _, _), *_ = builder(rng, T.DEV, [_base(k) for k in range(n)], attr)
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
    assert a == b and len(a) == 4 * 3 * 2 + 3  # plus one history control per stale case
    assert all((c["gold_turn"] is None) == c["control"] for c in a)
    assert {c["split"] for c in a} == {"dev", "heldout"}


def test_history_control_mentions_only_the_old_value_and_leaves_other_cases_alone(tmp_path, monkeypatch):
    builder, n, _ = BUILDERS["STALE_FACT"]
    for attr in ("city", "employer"):
        (pos, gold, _), (ctl, _, tids), history = builder(random.Random(2), T.DEV, [_base(k) for k in range(n)], attr)
        sessions, none, htids = history(random.Random(0))
        assert none is None and htids[:2] == tids[:2] and htids[2] in {t["id"] for t in T.STALE_HISTORY[attr]}
        hist, events = to_events("c", sessions), to_events("c", pos)
        diffs = [i for i, (x, y) in enumerate(zip(events, hist, strict=True)) if x["content"] != y["content"]]
        assert diffs == [gold]
        old_fact, update = events[0]["content"], events[2 + len(_base(0)[1])]["content"]
        old = next(v for v in T.CITIES + T.EMPLOYERS if v in old_fact)
        new = next(v for v in T.CITIES + T.EMPLOYERS if v in update and v != old)
        assert old in hist[gold]["content"] and new not in hist[gold]["content"]

    items = [{"question_id": f"q{i}", "haystack_session_ids": [f"s{i}_{k}" for k in range(4)],
              "haystack_dates": ["2023/01/01 (Sun) 10:00"] * 4,
              "haystack_sessions": [[{"role": r, "content": t} for r, t in _base(i * 10 + k)[1]] for k in range(4)]}
             for i in range(60)]
    path = tmp_path / "lme.json"
    path.write_text(json.dumps(items))
    import validation.goal1.mutate as m
    monkeypatch.setattr(m, "COUNTS", {"dev": 2, "heldout": 1})
    a = build_suite(path, seed=5)
    monkeypatch.setattr(T, "STALE_HISTORY", {k: [T.T("x", s, "Different {old}.") for s in (T.DEV, T.HELDOUT)]
                                             for k in ("city", "employer")})
    b = build_suite(path, seed=5)
    strip = lambda cases: [c for c in cases if not c["case_id"].endswith("-hist")]  # noqa: E731
    assert strip(a) == strip(b) and a != b


def test_wilson():
    lo, hi = wilson(17, 20)
    assert 0.6 < lo < 0.7 and 0.94 < hi < 0.96
    assert wilson(0, 0) == (0.0, 0.0)


def test_background_findings_shared_with_the_control_do_not_count_as_recall():
    rows = [{"case_id": "x-dev-000", "type": "STALE_FACT", "split": "dev", "attr": "city", "control": False,
             "found_turns": [3], "detected": True, "exact_turn": False},
            {"case_id": "x-dev-000-ctl", "type": "STALE_FACT", "split": "dev", "attr": "city", "control": True,
             "found_turns": [3], "false_positive": True}]
    agg = aggregate(rows)["dev|STALE_FACT|all"]
    assert agg["recall"]["k"] == 0 and agg["false_positive"]["k"] == 1


def test_pick_never_falls_back_across_splits():
    with pytest.raises(ValueError, match="no heldout template"):
        T.pick([T.T("a", T.DEV, "x")], T.HELDOUT, random.Random(0))


def test_history_controls_count_as_false_positives_and_get_their_own_row():
    rows = [{"case_id": "x-dev-000", "type": "STALE_FACT", "split": "dev", "attr": "city", "control": False,
             "found_turns": [3], "exact_turn": True},
            {"case_id": "x-dev-000-ctl", "type": "STALE_FACT", "split": "dev", "attr": "city", "control": True,
             "found_turns": [], "false_positive": False},
            {"case_id": "x-dev-000-hist", "type": "STALE_FACT", "split": "dev", "attr": "city", "control": True,
             "found_turns": [3], "false_positive": True}]
    agg = aggregate(rows)
    assert agg["dev|STALE_FACT|all"]["recall"]["k"] == 1  # the paired control, not the history one, nets recall
    assert agg["dev|STALE_FACT|all"]["false_positive"] == {**agg["dev|STALE_FACT|all"]["false_positive"], "k": 1, "n": 2}
    assert agg["dev|STALE_FACT|history_control"]["false_positive"]["n"] == 1
    assert base_id("x-dev-000-hist") == base_id("x-dev-000-ctl") == "x-dev-000"


def test_limit_keeps_history_controls_and_cost_charges_cached_calls():
    from types import SimpleNamespace

    from validation.goal1.__main__ import _cost, _first
    ids = ["stale_fact-heldout-000", "stale_fact-heldout-000-ctl", "stale_fact-heldout-000-hist",
           "stale_fact-heldout-001", "stale_fact-heldout-001-ctl"]
    cases = [{"case_id": i, "control": i.endswith(("-ctl", "-hist")),
              "events": [{"session_id": f"{i}:a"}, {"session_id": f"{i}:b"}]} for i in ids]
    assert [c["case_id"] for c in _first(cases, 1)] == ids[:3]
    usage = SimpleNamespace(by_role={"extractor": {"calls": 10, "cached": 6, "seconds": 8.0, "prompt_tokens": 0,
                                                    "completion_tokens": 0}})
    cost = _cost(cases, 60.0, SimpleNamespace(usage=usage))
    assert cost["sessions"] == 10 and cost["calls_per_100_sessions"] == 100.0
    assert cost["est_seconds_per_100_sessions"] == 200  # 10 calls at 2 s each (the uncached mean), per 10 sessions
    assert _cost(cases, 1.0, None) == {"sessions": 10, "wall_seconds": 1.0}
