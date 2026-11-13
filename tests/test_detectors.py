"""Ledger detectors: STALE_FACT, RECALL_MISS (judge mode), USER_REPAIR, and retrieve/use location."""
import json

from memdiag import Event, run
from memdiag.demo_data import DOCS, TRACES
from memdiag.detectors import mentions
from memdiag.judge import FakeJudge


def _ev(rows):
    out = []
    for i, r in enumerate(rows):
        user, role, content = r[:3]
        d = {"user_id": user, "session_id": "s", "ts": f"2026-03-01T10:{i:02d}:00", "role": role, "content": content}
        if len(r) > 3:
            d["memory"] = r[3]
        out.append(Event.from_dict(d, i))
    return out


MOVED = [
    ["maya", "user", "I live in Seattle."],
    ["maya", "user", "We just moved to Portland."],
]


def _stale(res):
    return [f for f in res["findings"] if f["type"] == "STALE_FACT"]


def test_mentions():
    assert mentions("Your $140k salary", "140000") and mentions("New York is big", "new york")
    assert not mentions("Newark", "new york") and not mentions("I have 14 days", "140000")


def test_stale_mention_without_a_judge():
    # "Seattle weather" is not a rule assertion, so only the ledger detector sees it.
    res = run(_ev(MOVED + [["maya", "assistant", "Seattle weather is rainy, so pack a coat."]]))
    (f,) = _stale(res)
    assert f["detector"] == "ledger.stale_mention" and f["confidence"] == 0.5
    assert (f["failing_turn"], f["evidence_turns"]) == (2, [1, 0])
    assert f["evidence_quote"] == "We just moved to Portland."
    m = res["metrics"]["fact_currency"]
    assert (m["failures"], m["opportunities"]) == (1, 1)
    # a ledger-only stale mention is not an assertion, so memory_faithfulness is not charged for it
    assert res["metrics"]["memory_faithfulness"]["opportunities"] == 0


def test_mentioning_both_values_is_not_stale_but_is_an_opportunity():
    res = run(_ev(MOVED + [["maya", "assistant", "Since you moved from Seattle to Portland, try OnPoint."]]))
    assert _stale(res) == []
    assert res["metrics"]["fact_currency"]["opportunities"] == 1


def test_judge_confirms_or_rejects_stale_candidates():
    rows = MOVED + [["maya", "assistant", "Seattle weather is rainy, so pack a coat."]]
    no = FakeJudge({"extract_facts": '{"facts": []}', "check_stale": '{"uses_old": false, "quote": ""}'})
    assert _stale(run(_ev(rows), judge=no)) == []
    invented = FakeJudge({"extract_facts": '{"facts": []}',
                          "check_stale": '{"uses_old": true, "quote": "you live in Seattle"}'})
    assert _stale(run(_ev(rows), judge=invented)) == []  # quote not in the reply
    yes = FakeJudge({"extract_facts": '{"facts": []}',
                     "check_stale": '{"uses_old": true, "quote": "Seattle weather is rainy"}'})
    (f,) = _stale(run(_ev(rows), judge=yes))
    assert f["detector"] == "llm.check_stale" and f["failing_quote"] == "Seattle weather is rainy"


def test_legacy_and_ledger_stale_findings_merge():
    res = run(_ev(MOVED + [["maya", "assistant", "Since you live in Seattle, try BECU."]]))
    (f,) = _stale(res)
    assert f["detector"] == "rules.memory_assertion"
    assert (res["metrics"]["fact_currency"]["failures"], res["metrics"]["fact_currency"]["opportunities"]) == (1, 1)


def test_judge_reask_any_ledger_fact():
    rows = [["u1", "user", "My daughter Maya is 7."], ["u1", "assistant", "Fun! How old is Maya now?"]]
    judge = FakeJudge({
        "extract_facts": json.dumps({"facts": [{"subject": "daughter", "attribute": "age", "value": "7",
                                                "quote": "My daughter Maya is 7"}]}),
        "check_reask": json.dumps({"asks_again": [{"key": "daughter.age", "quote": "How old is Maya now?"}]})})
    res = run(_ev(rows), judge=judge)
    (f,) = [f for f in res["findings"] if f["type"] == "RECALL_MISS"]
    assert f["detector"] == "llm.check_reask" and f["attribute"] == "daughter.age" and f["mode"] == "reask"
    m = res["metrics"]["recall_continuity"]
    assert (m["failures"], m["opportunities"]) == (1, 1)
    assert res["mode"] == "llm" and res["judge_usage"]["judge_reask"]["calls"] == 1


def test_judge_reask_rejects_unknown_keys_and_invented_quotes():
    rows = [["u1", "user", "My daughter Maya is 7."], ["u1", "assistant", "Fun! What games does she like?"]]
    judge = FakeJudge({
        "extract_facts": json.dumps({"facts": [{"subject": "daughter", "attribute": "age", "value": "7",
                                                "quote": "My daughter Maya is 7"}]}),
        "check_reask": json.dumps({"asks_again": [{"key": "daughter.age", "quote": "How old is she?"},
                                                  {"key": "user.city", "quote": "What games does she like?"}]})})
    assert [f for f in run(_ev(rows), judge=judge)["findings"] if f["type"] == "RECALL_MISS"] == []


def test_user_repair_signal_links_key_and_raises_confidence():
    rows = MOVED + [["maya", "assistant", "Since you live in Seattle, try BECU."],
                    ["maya", "user", "I already told you, we moved to Portland!"]]
    res = run(_ev(rows))
    (rep,) = [f for f in res["findings"] if f["type"] == "USER_REPAIR"]
    assert rep["failing_turn"] == 2 and rep["evidence_turns"] == [3] and rep["attribute"] == "user.city"
    assert _stale(res)[0]["confidence"] == 1.0
    assert res["repair_count"] == 1
    assert res["summary"]["memory_failures"] == 1  # the signal is not a failure of its own


def test_normal_follow_up_is_not_a_repair():
    rows = MOVED + [["maya", "assistant", "Try OnPoint."], ["maya", "user", "Thanks! What are their hours?"]]
    assert run(_ev(rows))["repair_count"] == 0


def test_location_retrieve_vs_use():
    asked = "Since you live in Seattle, try BECU."
    had_it = run(_ev(MOVED + [["maya", "assistant", asked, [{"id": "m1", "text": "User lives in Portland."}]]]))
    missing = run(_ev(MOVED + [["maya", "assistant", asked, [{"id": "m1", "text": "User lives in Seattle."}]]]))
    no_memory = run(_ev(MOVED + [["maya", "assistant", asked]]))
    assert _stale(had_it)[0]["location"] == "use"
    assert _stale(missing)[0]["location"] == "retrieve"
    assert _stale(no_memory)[0]["location"] is None


def test_failures_never_exceed_opportunities():
    for events in (_ev(MOVED + [["maya", "assistant", "Seattle or Portland? Seattle has BECU."]]),
                   [Event.from_dict(t, i) for i, t in enumerate(TRACES)]):
        for m in run(events, DOCS)["metrics"].values():
            assert m["failures"] <= m["opportunities"], m


def test_cli_diagnose_with_unreachable_model_exits_2(tmp_path, capsys):
    import socket

    from memdiag.cli import main
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    log = tmp_path / "log.jsonl"
    log.write_text(json.dumps({"user_id": "u", "session_id": "s", "ts": "2026-01-01T00:00:00", "role": "user",
                               "content": "I live in Seattle and I love it."}) + "\n")
    code = main(["diagnose", str(log), "--model", "qwen2.5:7b", "--base-url", f"http://127.0.0.1:{port}/v1",
                 "--cache", str(tmp_path / "c")])
    assert code == 2 and "ollama serve" in capsys.readouterr().err


def test_ledger_reask_denominator_covers_every_legacy_reask_turn():
    for events in ([Event.from_dict(t, i) for i, t in enumerate(TRACES)],
                   _ev(MOVED + [["maya", "assistant", "Where do you live?"], ["maya", "assistant", "Try OnPoint."]])):
        opp = run(events, DOCS)["stats"]["opportunities"]
        assert opp["legacy_known_fact_turns"] <= opp["known_fact_turns"]


def test_rule_reask_over_ledger_facts_and_judge_cannot_veto():
    rows = [["u1", "user", "My daughter Maya loves chess."], ["u1", "user", "Maya is 7, she says."],
            ["u1", "assistant", "Happy to help! How old is Maya, and what is she into?"]]
    facts = {"My daughter Maya loves chess.": [{"subject": "daughter", "attribute": "name", "value": "Maya",
                                                "quote": "My daughter Maya"}],
             "Maya is 7, she says.": [{"subject": "daughter", "attribute": "age", "value": "7", "quote": "Maya is 7"}]}

    def extract(text):
        return json.dumps({"facts": next((v for k, v in facts.items() if text.endswith(k)), [])})

    judge = FakeJudge({"extract_facts": extract, "check_stale": '{"uses_old": false}',
                       "check_reask": '{"asks_again": []}'})  # the 7B judge's real answer on this case
    res = run(_ev(rows), judge=judge)
    (f,) = [f for f in res["findings"] if f["type"] == "RECALL_MISS"]
    assert (f["attribute"], f["detector"], f["confidence"]) == ("daughter.age", "ledger.reask_pattern", 0.6)
    assert f["failing_quote"] == "How old is Maya, and what is she into?"


def test_reask_pattern_needs_the_right_subject():
    rows = [["u1", "user", "My daughter Maya is 7 and I love it."], ["u1", "assistant", "How old is your dog?"]]
    extract = json.dumps({"facts": [{"subject": "daughter", "attribute": "age", "value": "7",
                                     "quote": "My daughter Maya is 7"}]})
    judge = FakeJudge({"extract_facts": extract, "check_reask": '{"asks_again": []}'})
    assert [f for f in run(_ev(rows), judge=judge)["findings"] if f["type"] == "RECALL_MISS"] == []
