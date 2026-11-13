"""The fact ledger: what each user said about themselves, when, and in their own words.

    ledger = build_ledger(events, judge=OpenAICompatJudge("qwen2.5:7b"))   # judge=None: rules only
    ledger.current("maya", "user.city", before_turn=12)                     # the live LedgerItem, or None

Every item quotes the user's message verbatim. An update links the old item to the new one (`superseded_by`)
and a deletion request closes it (`revoked_at_turn`). Keys are normalized deterministically, so "I moved to
Denver" and "we relocated to Austin" land on the same key `user.city` whichever extractor produced them.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional

from .text import numbers

SELF = {"user", "i", "me", "myself", "self", "speaker", "mine", "im"}
FILLER = {"my", "our", "the", "a", "an", "of", "his", "her", "their"}
ATTRIBUTE_SYNONYMS = {
    "city": {"location", "home_city", "current_city", "residence", "home", "lives_in", "city_of_residence",
             "current_location", "place_of_residence"},
    "income": {"salary", "annual_income", "annual_salary", "pay", "earnings"},
    "employer": {"company", "workplace", "employer_name", "work_place", "works_at", "workplace_name"},
    "job_title": {"job", "occupation", "role", "position", "profession", "title"},
    "name": {"first_name", "full_name"},
    "birthday": {"dob", "date_of_birth", "birth_date"},
}
_SYNONYM = {alias: canon for canon, aliases in ATTRIBUTE_SYNONYMS.items() for alias in aliases}


def _tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if t]


def normalize_subject(subject: str) -> str:
    """'I', 'user|myself', '' -> 'user'; 'my daughter' -> 'daughter'; 'user|Maya' -> 'maya'."""
    rest = [t for t in _tokens(subject) if t not in SELF and t not in FILLER]
    return "_".join(rest) or "user"


def normalize_attribute(attribute: str) -> str:
    """Lowercase snake_case with synonyms folded: 'Home City' -> 'city', 'loan:car loan' -> 'loan_car_loan'."""
    toks = _tokens(attribute)
    while toks and toks[0] in SELF | FILLER:
        toks = toks[1:]
    name = "_".join(toks)
    return _SYNONYM.get(name, name)


def normalize_key(subject: str, attribute: str) -> str:
    return f"{normalize_subject(subject)}.{normalize_attribute(attribute)}"


def normalize_value(value) -> str:
    """For comparing values: '$140k' == '140000', 'Denver.' == 'denver'."""
    text = str(value or "")
    nums = numbers(text)
    leftover = re.sub(r"(\d[\d,]*(?:\.\d+)?)\s*[kKmM]?\b|[$€£,\s]", "", text)
    if len(nums) == 1 and not leftover:
        n = nums[0]
        return str(int(n)) if n == int(n) else str(n)
    return " ".join(_tokens(text))


@dataclass
class LedgerItem:
    item_id: str
    user_id: str
    key: str
    subject: str
    attribute: str
    value: str
    source_turn: int
    ts: datetime
    quote: str
    extractor: str  # "rules", "llm" or "rules+llm"
    superseded_by: Optional[str] = None
    revoked_at_turn: Optional[int] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        return d
