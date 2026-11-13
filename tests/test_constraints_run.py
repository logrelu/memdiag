"""CONSTRAINT_DROP through run(), metrics and the report."""
from memdiag import Event


def _events(rows):
    return [Event.from_dict({"user_id": "u1", "session_id": s, "ts": f"2026-03-01T10:{i:02d}:00", "role": r,
                             "content": c}, i) for i, (s, r, c) in enumerate(rows)]


def test_run_reports_constraint_retention_and_cards():
    from memdiag import run
    from memdiag.findings_report import findings_html
    events = _events([["s1", "user", "Keep your answers under 6 words."], ["s1", "assistant", "Short reply."],
                      ["s1", "assistant", "This second reply runs well past the six word limit."]])
    res = run(events)
    m = res["metrics"]["constraint_retention"]
    assert (m["failures"], m["opportunities"], m["score"]) == (1, 2, 0.5)
    page = findings_html(res, events)
    assert "CONSTRAINT_DROP" in page and "<mark>under 6 words</mark>" in page


def test_no_instructions_means_not_applicable():
    from memdiag import run
    m = run(_events([["s1", "user", "Hi there, I need help."], ["s1", "assistant", "Sure, happy to help."]]))["metrics"]
    assert m["constraint_retention"]["score"] is None
