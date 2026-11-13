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


@pytest.mark.parametrize("text", [
    "No emojis in my wedding invite.", "Use bullet points for the slides.", "Write an essay under 500 words.",
    "Reply in Spanish to this email I wrote.", "Write me a poem in 3 sentences.", "Can you reply in one sentence?",
    "Write a function that returns JSON only.", "Please write in lowercase letters for my sign.",
    "Never use bullet points in my resume.", "Stop using emojis in the commit messages.",
    "I wrote it in Spanish.", "The report should be under 10 words.",
])
def test_one_off_tasks_are_not_standing_instructions(text):
    assert extract_constraints(text) == []  # review cases: none of these govern later replies


@pytest.mark.parametrize("text,kind", [
    ("Max 50 words.", "max_words"), ("Only use lowercase.", "lowercase"), ("Never mention pricing.", "banned_word"),
    ("Please respond in Spanish from now on.", "language"), ("Answer only in German.", "language"),
    ("From now on, keep your answers under 30 words.", "max_words"), ("No emojis please.", "no_emoji"),
])
def test_common_instruction_phrasings(text, kind):
    assert [k for k, _, _ in extract_constraints(text)] == [kind]


def test_revoke_after_add_in_the_same_message():
    events = _events([["s1", "user", "Reply in under 5 words. Actually, you can go longer."],
                      ["s1", "assistant", "Sure, here is a longer answer than five words."]])
    assert detect_constraints(events) == ([], 0)


@pytest.mark.parametrize("override", ["Translate 'hello' into English.", "Translate this to German: hello."])
def test_one_off_translation_skips_the_language_check(override):
    events = _events([["s1", "user", "Please reply in French."], ["s1", "user", override],
                      ["s1", "assistant", "Hello is a greeting that people use in the morning and the evening."]])
    findings, pairs = detect_constraints(events)
    assert findings == [] and pairs == 0


def test_check_counting_and_format_edge_cases():
    from memdiag.constraints import Constraint, check
    words = Constraint("max_words", "4", 0, "")
    assert check(words, "It's 3.5 - well-known.")[1] == "3 words"
    sentences = Constraint("max_sentences", "1", 0, "")
    assert check(sentences, "Dr. Smith said e.g. this is 3.5 fine.")[0] is True
    no_bullets = Constraint("no_bullets", "", 0, "")
    assert check(no_bullets, "Run:\n```\n- a\n```")[0] is True
    assert check(Constraint("json_only", "", 0, ""), "```JSON\n{\"a\": 1}\n```")[0] is True
    no_emoji = Constraint("no_emoji", "", 0, "")
    assert check(no_emoji, "Done ✓ ★ → next") [0] is True and check(no_emoji, "Done 🎉")[0] is False
    lower = Constraint("lowercase", "", 0, "")
    assert check(lower, "use `NULL` and the API here")[0] is True and check(lower, "Hello there")[0] is False
