from memdiag import Event, run
from memdiag.demo_data import DOCS, TRACES
from memdiag.extract import RuleExtractor


def _res():
    return run([Event.from_dict(t, i) for i, t in enumerate(TRACES)], DOCS)


def test_demo_finds_each_failure_type():
    cats = _res()["summary"]["by_category"]
    for c in ["stale_memory", "failed_deletion", "cross_user_leak", "hallucinated_memory",
              "forgotten_memory", "retrieval_miss", "ignored_context", "context_overload"]:
        assert cats.get(c), c
    assert cats["stale_memory"] == 2


def test_memory_vs_retrieval_split():
    s = _res()["summary"]
    assert (s["memory_failures"], s["retrieval_failures"]) == (6, 3)


def test_correct_answer_not_flagged():
    res = _res()
    assert not any("4.10% APY" in f["turn"] for f in res["findings"])


def test_strategy_ranking():
    rows = {r["strategy"]: r for r in _res()["strategies"]}
    assert rows["Profile + deletion"]["accuracy"] == 1.0
    assert rows["Full history in context"]["stale"] > 0
    assert rows["Top-k search, shared index"]["cross_user"] > 0


def test_extractor_basics():
    ex = RuleExtractor()
    assert ("city", "Portland") in ex.user_facts("We just moved to Portland.")
    assert ("income", "140000") in ex.user_facts("my salary is now $140k")
    assert ex.deletions("Please forget my income.") == ["income"]
    assert ("city", "Seattle") in ex.assertions("Since you live in Seattle, try BECU.")
    assert ex.user_facts("the weather in Seattle is nice") == []
