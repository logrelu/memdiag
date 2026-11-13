"""Every Finding points at a turn and quotes it verbatim (docs/STABILITY.md, Finding fields)."""
from memdiag import Event, run
from memdiag.demo_data import DOCS, TRACES
from memdiag.detect import _sentence
from memdiag.schema import TYPES


def _t(user, ts, role, content, sess="s1"):
    return {"user_id": user, "session_id": sess, "ts": f"2026-03-01T10:{ts:02d}:00", "role": role, "content": content}


def _run(rows, docs=None):
    events = [Event.from_dict(t, i) for i, t in enumerate(rows)]
    return events, run(events, docs)


def test_every_demo_finding_is_localized_and_quotes_verbatim():
    events, res = _run(TRACES, DOCS)
    by_index = {e.index: e for e in events}
    assert res["findings"]
    for f in res["findings"]:
        failing = by_index[f["failing_turn"]]
        assert failing.role == "assistant"
        assert f["failing_quote"] and f["failing_quote"] in failing.content
        assert f["detector"].startswith("rules.") and f["detector_version"]
        assert f["type"] == TYPES[f["category"]]
        for i in f["evidence_turns"]:
            assert f["evidence_quote"] in by_index[i].content


def test_stale_fact_points_at_the_update():
    rows = [
        _t("maya", 0, "user", "I live in Seattle."),
        _t("maya", 1, "user", "We just moved to Portland."),
        _t("maya", 2, "assistant", "Happy to help. Since you live in Seattle, try BECU."),
    ]
    _, res = _run(rows)
    (f,) = [f for f in res["findings"] if f["type"] == "STALE_FACT"]
    assert (f["failing_turn"], f["evidence_turns"]) == (2, [1])
    assert f["failing_quote"] == "Since you live in Seattle, try BECU."
    assert f["evidence_quote"] == "We just moved to Portland."
    assert f["covariates"]["turn_distance"] == 1


def test_cross_user_leak_quotes_the_other_users_message():
    rows = [
        _t("dev", 0, "user", "I live in Austin."),
        _t("maya", 1, "user", "I live in Seattle."),
        _t("maya", 2, "assistant", "Since you live in Austin, try UFCU."),
    ]
    _, res = _run(rows)
    (f,) = [f for f in res["findings"] if f["type"] == "CROSS_USER_LEAK"]
    assert f["evidence_turns"] == [0] and f["evidence_quote"] == "I live in Austin."


def test_reask_mode_and_same_timestamp_turns_count_separately():
    rows = [
        _t("maya", 0, "user", "I live in Seattle."),
        _t("maya", 1, "assistant", "Where do you live?"),
        _t("maya", 1, "assistant", "Sorry, where do you live?"),  # same session and ts, another turn
    ]
    _, res = _run(rows)
    reasks = [f for f in res["findings"] if f["type"] == "RECALL_MISS"]
    assert [f["mode"] for f in reasks] == ["reask", "reask"]
    m = res["metrics"]["recall_continuity"]
    assert (m["failures"], m["opportunities"]) == (2, 2)


def test_sentence_falls_back_to_whole_text():
    assert _sentence("No match here", hint="Seattle") == "No match here"
    assert _sentence("A. With your $140k salary, yes.", hint="140000") == "With your $140k salary, yes."


def test_numeric_quote_matches_the_number_not_a_prefix():
    # Review case: "14 days" must not be quoted for an asserted 140000.
    assert _sentence("Yes. 14 days ok. Total 1,40,000.", hint="140000") == "Total 1,40,000."
    assert _sentence("Ok. Your $140k salary works.", hint="140000") == "Your $140k salary works."


def test_cross_user_leak_has_no_cross_user_turn_distance():
    rows = [
        _t("dev", 0, "user", "I live in Austin."),
        _t("maya", 1, "user", "I live in Seattle."),
        _t("maya", 2, "assistant", "Since you live in Austin, try UFCU."),
    ]
    _, res = _run(rows)
    (f,) = [f for f in res["findings"] if f["type"] == "CROSS_USER_LEAK"]
    assert "turn_distance" not in f["covariates"]


def test_events_without_indices_are_numbered_in_order():
    rows = [
        _t("maya", 0, "user", "I live in Seattle."),
        _t("maya", 1, "assistant", "Where do you live?"),
        _t("maya", 2, "assistant", "Where do you live, again?"),
    ]
    res = run([Event.from_dict(t) for t in rows])  # every index defaults to 0
    assert sorted(f["failing_turn"] for f in res["findings"]) == [1, 2]
    assert res["metrics"]["recall_continuity"]["failures"] == 2
