import pytest

from memdiag import Event, check_thresholds, compute_metrics, run
from memdiag.cli import main
from memdiag.demo_data import DOCS, TRACES


def _t(user, ts, role, content):
    return {"user_id": user, "session_id": "s1", "ts": f"2026-03-01T10:{ts:02d}:00", "role": role, "content": content}


# maya moves Seattle -> Portland. Agent is right once (Portland), stale once (Seattle).
# dev states a city too, so "shared attribute" opportunities exist for maya.
MIXED = [
    _t("dev", 0, "user", "I live in Austin."),
    _t("maya", 1, "user", "I live in Seattle."),
    _t("maya", 2, "user", "We just moved to Portland."),
    _t("maya", 3, "assistant", "Since you live in Portland, try a local credit union."),
    _t("maya", 4, "assistant", "Since you live in Seattle, try BECU."),
]


def _run(rows):
    return run([Event.from_dict(t, i) for i, t in enumerate(rows)])


def test_scores_have_explicit_denominators():
    m = _run(MIXED)["metrics"]
    assert m["memory_faithfulness"]["opportunities"] == 2
    assert m["memory_faithfulness"]["failures"] == 1
    assert m["memory_faithfulness"]["score"] == 0.5
    # both claims come after maya's update, so both are chances to use the latest value
    assert (m["fact_currency"]["failures"], m["fact_currency"]["opportunities"]) == (1, 2)
    assert m["fact_currency"]["score"] == 0.5


def test_not_applicable_is_none_not_perfect():
    m = _run(MIXED)["metrics"]
    assert m["deletion_compliance"]["opportunities"] == 0
    assert m["deletion_compliance"]["score"] is None
    # nobody has given a fact yet, so there was nothing to re-ask
    m = _run([_t("dev", 0, "assistant", "Where do you live?")])["metrics"]
    assert m["recall_continuity"]["opportunities"] == 0
    assert m["recall_continuity"]["score"] is None


def test_recall_continuity_counts_turns_that_could_reask():
    # Regression: the denominator used to count only the re-asks, so the score was always 0.
    rows = [
        _t("maya", 0, "user", "I live in Seattle."),
        _t("maya", 1, "assistant", "Where do you live? I want to suggest a bank."),
        _t("maya", 2, "assistant", "Since you live in Seattle, try BECU."),
        _t("maya", 3, "assistant", "Happy to help with anything else."),
        _t("maya", 4, "assistant", "Where do you live? Where are you located?"),  # two re-asks, one turn
    ]
    m = _run(rows)["metrics"]["recall_continuity"]
    assert (m["failures"], m["opportunities"], m["score"]) == (2, 4, 0.5)


def test_scores_bounded():
    for res in (_run(MIXED), run([Event.from_dict(t, i) for i, t in enumerate(TRACES)], DOCS)):
        for m in res["metrics"].values():
            assert m["score"] is None or 0.0 <= m["score"] <= 1.0


def test_deletion_counted_once_per_fact():
    rows = [
        _t("dev", 0, "user", "My salary is $140k."),
        _t("dev", 1, "user", "Please forget my income."),
        _t("dev", 2, "assistant", "With your $140k salary, a mortgage is feasible."),
        _t("dev", 3, "assistant", "At $140k income you qualify."),
    ]
    m = _run(rows)["metrics"]["deletion_compliance"]
    assert (m["failures"], m["opportunities"], m["score"]) == (1, 1, 0.0)


def test_threshold_gate():
    metrics = compute_metrics(_run(MIXED)["findings"], _run(MIXED)["stats"]["opportunities"])
    assert check_thresholds(metrics, {"memory_faithfulness": 0.4}) == []
    assert check_thresholds(metrics, {"memory_faithfulness": 0.9})
    assert check_thresholds(metrics, {"deletion_compliance": 0.99}) == []  # n/a never fails
    assert "unknown metric" in check_thresholds(metrics, {"nope": 0.5})[0]


def test_cli_exit_codes(capsys):
    assert main(["demo", "--no-color", "--fail-under", "groundedness=0.5"]) == 0
    assert main(["demo", "--no-color", "--fail-under", "memory_faithfulness=0.9"]) == 1
    assert main(["demo", "--no-color", "--fail-under", "bogus"]) == 2
    err = capsys.readouterr().err
    assert "FAIL: memory_faithfulness" in err and "METRIC=NUMBER" in err


@pytest.mark.parametrize("name", ["memory_faithfulness", "fact_currency", "deletion_compliance",
                                  "user_isolation", "groundedness", "recall_continuity"])
def test_every_metric_is_reported(name):
    assert name in _run(MIXED)["metrics"]
