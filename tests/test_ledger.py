"""The fact ledger on hand-written cases (tests/fixtures/ledger_cases.json), with a scripted FakeJudge."""
import json
from pathlib import Path

import pytest

from memdiag import Event
from memdiag.judge import FakeJudge
from memdiag.ledger import build_ledger

CASES = json.loads((Path(__file__).parent / "fixtures" / "ledger_cases.json").read_text())


def _events(rows):
    return [Event.from_dict({"user_id": u, "session_id": "s", "ts": f"2026-03-01T10:{i:02d}:00", "role": r,
                             "content": c}, i) for i, (u, r, c) in enumerate(rows)]


def _judge(llm: dict):
    def reply(prompt_text):
        for message, facts in llm.items():
            if prompt_text.endswith(message):
                return facts if isinstance(facts, str) else json.dumps({"facts": facts})
        return json.dumps({"facts": []})
    return FakeJudge({"extract_facts": reply})


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_ledger_case(case):
    ledger = build_ledger(_events(case["events"]), judge=_judge(case.get("llm", {})))
    exp = case["expect"]
    for ref, value in exp.get("current", {}).items():
        user, key = ref.split("|")
        item = ledger.current(user, key)
        assert (item.value if item else None) == value, ref
    for ref, extractor in exp.get("extractors", {}).items():
        assert ledger.current(*ref.split("|")).extractor == extractor, ref
    for ref, quote in exp.get("quotes", {}).items():
        assert ledger.current(*ref.split("|")).quote == quote, ref
    if "superseded" in exp:
        got = []
        by_id = {i.item_id: i for i in ledger.items}
        for i in ledger.items:
            if i.superseded_by:
                got.append([f"{i.user_id}|{i.key}", i.value, by_id[i.superseded_by].value])
        assert got == exp["superseded"]
    if "revoked" in exp:
        assert sorted({f"{i.user_id}|{i.key}" for i in ledger.items if i.revoked_at_turn is not None}) == exp["revoked"]
    for stat in ("dropped", "llm_messages", "items", "messages"):
        if stat in exp:
            assert ledger.stats[stat] == exp[stat], stat


def test_every_quote_is_verbatim_from_its_source_turn():
    for case in CASES:
        events = _events(case["events"])
        ledger = build_ledger(events, judge=_judge(case.get("llm", {})))
        for item in ledger.items:
            assert item.quote and item.quote in events[item.source_turn].content, (case["name"], item)


def test_rules_only_without_a_judge():
    ledger = build_ledger(_events([["maya", "user", "I live in Seattle."],
                                   ["maya", "user", "Update: we relocated to Austin for my new job."]]))
    assert ledger.current("maya", "user.city").value == "Seattle"  # rules miss "we relocated"; that's the LLM's job
    assert ledger.stats["llm_messages"] == 0


def test_current_respects_the_turn():
    ledger = build_ledger(_events([["maya", "user", "I live in Seattle."], ["maya", "user", "We just moved to Portland."],
                                   ["maya", "user", "Please forget where I live."]]))
    assert ledger.current("maya", "user.city", before_turn=1).value == "Seattle"
    assert ledger.current("maya", "user.city", before_turn=2).value == "Portland"
    assert ledger.current("maya", "user.city") is None
    assert [i.value for i in ledger.history("maya", "user.city")] == ["Seattle", "Portland"]


def test_cli_ledger_rules_only(tmp_path, capsys):
    from memdiag.cli import main
    log = tmp_path / "log.jsonl"
    rows = [{"user_id": "maya", "session_id": "s", "ts": f"2026-03-01T10:0{i}:00", "role": "user", "content": c}
            for i, c in enumerate(["I live in Seattle.", "We just moved to Portland."])]
    log.write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = tmp_path / "ledger.jsonl"
    assert main(["ledger", str(log), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "user.city" in printed and "Seattle -> Portland" in printed and "1 updates" in printed
    assert [json.loads(line)["value"] for line in out.read_text().splitlines()] == ["Seattle", "Portland"]


def test_unknown_turn_is_a_clear_error():
    ledger = build_ledger(_events([["maya", "user", "I live in Seattle."]]))
    with pytest.raises(ValueError, match="turn 99 is not in this log"):
        ledger.current("maya", "user.city", before_turn=99)


def test_cli_ledger_bad_inputs_exit_2(tmp_path, capsys):
    from memdiag.cli import main
    assert main(["ledger", str(tmp_path / "missing.jsonl")]) == 2
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"user_id": "u", "role": "user", "content": "x", "ts": "2026-01-01T00:00:00"}\nnot json\n')
    assert main(["ledger", str(bad)]) == 2
    assert "line 2 is not valid JSON" in capsys.readouterr().err


def test_known_people_are_passed_to_the_extractor():
    seen = []

    def reply(text):
        seen.append(text)
        if text.endswith("My daughter Maya loves chess."):
            return json.dumps({"facts": [{"subject": "daughter", "attribute": "name", "value": "Maya",
                                          "quote": "My daughter Maya"}]})
        return json.dumps({"facts": [{"subject": "daughter", "attribute": "age", "value": "7", "quote": "Maya turns 7"}]})

    events = _events([["u1", "user", "My daughter Maya loves chess."], ["u1", "user", "Maya turns 7 next month, she says."]])
    ledger = build_ledger(events, judge=FakeJudge({"extract_facts": reply}))
    assert "- (none yet)" in seen[0] and "- daughter: Maya" in seen[1]
    assert ledger.current("u1", "daughter.age").value == "7"
    assert ledger.known_people("u1") == [("daughter", "Maya")]
