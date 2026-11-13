"""CONSTRAINT_DROP on hand-written cases (tests/fixtures/constraint_cases.json). No model involved."""
import json
from pathlib import Path

import pytest

from memdiag import Event
from memdiag.constraints import detect_constraints, detect_language, extract_constraints

CASES = json.loads((Path(__file__).parent / "fixtures" / "constraint_cases.json").read_text())


def _events(rows):
    return [Event.from_dict({"user_id": "u1", "session_id": s, "ts": f"2026-03-01T10:{i:02d}:00", "role": r,
                             "content": c}, i) for i, (s, r, c) in enumerate(rows)]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_constraint_case(case):
    events = _events(case["events"])
    findings, pairs = detect_constraints(events)
    exp = case["expect"]
    assert sorted([f.failing_turn, f.attribute.split(".")[1]] for f in findings) == sorted(exp["violations"])
    assert pairs == exp["opportunities"]
    if "failing_quotes" in exp:
        assert [f.failing_quote for f in findings] == exp["failing_quotes"]
    if "expected" in exp:
        assert [f.expected for f in findings] == exp["expected"]
    by_index = {e.index: e for e in events}
    for f in findings:  # quotes are verbatim from their turns
        assert f.failing_quote in by_index[f.failing_turn].content
        assert f.evidence_quote in by_index[f.evidence_turns[0]].content
        assert f.type == "CONSTRAINT_DROP" and f.detector.startswith("rules.constraint_")


def test_extraction_params():
    got = {(k, p) for k, p, _ in extract_constraints("Reply in Spanish and keep it under 8 words. Don't use the word 'synergy'.")}
    assert got == {("language", "es"), ("max_words", "8"), ("banned_word", "synergy")}
    assert extract_constraints("Reply in two sentences.")[0][:2] == ("max_sentences", "2")


def test_language_id():
    assert detect_language("Claro, la mejor época para visitar es en la primavera.") == "es"
    assert detect_language("The best time to visit is in the spring when it is warm.") == "en"
    assert detect_language("OK, thanks.") is None
