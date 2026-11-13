"""memdiag run and the findings report."""

import re

from memdiag import Event, run
from memdiag.demo_data import DOCS, TRACES
from memdiag.findings_report import cant_see, findings_html


def _ev(rows):
    out = []
    for i, r in enumerate(rows):
        d = {"user_id": r[0], "session_id": "s", "ts": f"2026-03-01T10:{i:02d}:00", "role": r[1], "content": r[2]}
        if len(r) > 3:
            d["memory"] = r[3]
        out.append(Event.from_dict(d, i))
    return out


STALE = [["maya", "user", "I live in Seattle."], ["maya", "user", "We just moved to Portland."],
         ["maya", "assistant", "Since you live in Seattle, try BECU."]]


def test_every_finding_gets_a_card_with_both_quotes_marked():
    events = [Event.from_dict(t, i) for i, t in enumerate(TRACES)]
    res = run(events, DOCS)
    page = findings_html(res, events)
    cards = re.findall(r'<article class="card">.*?</article>', page, re.S)
    assert len(cards) == sum(f["class"] in ("memory", "retrieval") for f in res["findings"])
    (card,) = [c for c in findings_html(run(_ev(STALE)), _ev(STALE)).split("<article")[1:] if "STALE_FACT" in c]
    assert "<mark>We just moved to Portland.</mark>" in card
    assert "<mark>Since you live in Seattle, try BECU.</mark>" in card


def test_log_markup_is_escaped():
    rows = [["eve", "user", "I live in Seattle. <script>alert(1)</script>"], ["eve", "user", "We just moved to Portland."],
            ["eve", "assistant", "Since you live in Seattle <img src=x onerror=alert(1)>, try BECU."]]
    page = findings_html(run(_ev(rows)), _ev(rows))
    assert "<script" not in page.lower() and "<img" not in page.lower()
    assert "&lt;img src=x onerror=alert(1)&gt;" in page  # shown, escaped, in the failing turn


def test_cant_see_reflects_the_run():
    plain = run(_ev(STALE))
    lines = " ".join(cant_see(plain, _ev(STALE)))
    assert "No memory context was logged" in lines and "Rules mode" in lines
    assert "deletion_compliance</b> is n/a" in lines and "No findings is not proof" in lines
    with_memory = STALE[:2] + [STALE[2] + [[{"id": "m1", "text": "User lives in Seattle."}]]]
    assert "No memory context" not in " ".join(cant_see(run(_ev(with_memory)), _ev(with_memory)))


def test_location_shows_on_cards():
    rows = STALE[:2] + [STALE[2] + [[{"id": "m1", "text": "User lives in Portland."}]]]
    page = findings_html(run(_ev(rows)), _ev(rows))
    assert '<span class="pill">use</span>' in page and "<b>1</b> use" in page
