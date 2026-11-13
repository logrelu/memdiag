"""Known limits of the v0 rule-based extractor.

These cases use phrasing the regexes were not written for. They are expected
to fail until an LLM-based extractor replaces RuleExtractor.
"""
from pathlib import Path

import pytest

from memdiag import run_files

UNSEEN = Path(__file__).parent.parent / "examples" / "unseen_phrasing.jsonl"


@pytest.mark.xfail(reason="v0 regexes miss 'we relocated to' and 'left X for a role at Y'", strict=True)
def test_detects_stale_city_and_employer_on_unseen_phrasing():
    cats = run_files(str(UNSEEN))["summary"]["by_category"]
    assert cats.get("stale_memory") == 2


@pytest.mark.xfail(reason="'Nope' is not in the v0 pushback list", strict=True)
def test_counts_nope_as_user_pushback():
    assert run_files(str(UNSEEN))["stats"]["user_flagged_turns"] >= 1


@pytest.mark.xfail(reason="legacy Timeline orders by timestamp only; with identical timestamps a fact stated "
                          "earlier in the log is not 'before' a later assertion, so one assertion is both "
                          "hallucinated and stale", strict=True)
def test_identical_timestamps_do_not_double_count():
    from memdiag import Event, run
    rows = [("user", "I live in Seattle."), ("user", "We just moved to Portland."),
            ("assistant", "Since you live in Seattle, try BECU.")]
    events = [Event.from_dict({"user_id": "u", "session_id": "s", "ts": "2026-01-01T00:00:00", "role": r,
                               "content": c}, i) for i, (r, c) in enumerate(rows)]
    cats = run(events)["summary"]["by_category"]
    assert cats.get("hallucinated_memory") is None and cats.get("stale_memory") == 1
