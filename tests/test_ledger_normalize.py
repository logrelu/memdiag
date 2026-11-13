import pytest

from memdiag.ledger import normalize_attribute, normalize_key, normalize_subject, normalize_value


@pytest.mark.parametrize("raw,expected", [
    ("user", "user"), ("I", "user"), ("me", "user"), ("", "user"), (None, "user"),
    ("user|myself", "user"),  # the walkthrough's broken key
    ("my daughter", "daughter"), ("Daughter", "daughter"), ("user|Maya", "maya"), ("best friend", "best_friend"),
])
def test_subjects(raw, expected):
    assert normalize_subject(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("city", "city"), ("Home City", "city"), ("location", "city"), ("current_location", "city"),
    ("salary", "income"), ("company", "employer"), ("occupation", "job_title"),
    ("my_city", "city"), ("user.city", "city"), ("loan:car loan", "loan_car_loan"), ("Credit Score", "credit_score"),
])
def test_attributes(raw, expected):
    assert normalize_attribute(raw) == expected


def test_walkthrough_keys_now_collide():
    # The LLM produced these for Denver and Austin; they must be one key.
    assert normalize_key("user|myself", "city") == normalize_key("user", "city") == "user.city"
    assert normalize_key("user", "location") == "user.city"


@pytest.mark.parametrize("a,b", [("$140k", "140000"), ("140,000", "140000"), ("Denver.", "denver"),
                                 ("New  York", "new york"), ("7", "7")])
def test_equal_values(a, b):
    assert normalize_value(a) == normalize_value(b)


@pytest.mark.parametrize("a,b", [("Denver", "Austin"), ("$140k", "$150k"), ("7 years", "7")])
def test_different_values(a, b):
    assert normalize_value(a) != normalize_value(b)
