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
