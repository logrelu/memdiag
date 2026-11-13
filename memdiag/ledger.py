"""The fact ledger: what each user said about themselves, when, and in their own words.

    ledger = build_ledger(events, judge=OpenAICompatJudge("qwen2.5:7b"))   # judge=None: rules only
    ledger.current("maya", "user.city", before_turn=12)                     # the live LedgerItem, or None

Every item quotes the user's message verbatim. An update links the old item to the new one (`superseded_by`)
and a deletion request closes it (`revoked_at_turn`). Keys are normalized deterministically, so "I moved to
Denver" and "we relocated to Austin" land on the same key `user.city` whichever extractor produced them.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Optional

from .extract import RuleExtractor
from .prompt import load_prompt
from .schema import Event
from .text import numbers, sentence

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


FIRST_PERSON = re.compile(r"\b(i|i'm|im|i've|i'd|my|me|mine|we|we're|we've|our|us)\b", re.I)


def worth_extracting(text: str) -> bool:
    """Cheap filter before any LLM call: a first-person message that isn't only questions."""
    if not FIRST_PERSON.search(text):
        return False
    parts = [p for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]
    return any(not p.rstrip().endswith("?") for p in parts)


def quote_span(quote: str, text: str) -> Optional[str]:
    """The exact span of `text` that `quote` matches, ignoring case and runs of whitespace; None if absent."""
    words = (quote or "").split()
    if not words:
        return None
    m = re.search(r"\s+".join(map(re.escape, words)), text, re.I)
    return m.group(0) if m else None


class Ledger:
    def __init__(self, order: dict[int, int]):
        self.items: list[LedgerItem] = []
        self.dropped: list[dict] = []  # LLM facts rejected, with the reason, for audit
        self.stats = {"messages": 0, "llm_messages": 0, "items": 0, "dropped": 0}
        self._order = order  # event index -> position in time order
        self._by_key: dict[tuple, list[LedgerItem]] = defaultdict(list)

    def _before(self, item_turn: int, turn: Optional[int]) -> bool:
        return turn is None or self._order[item_turn] < self._order[turn]

    def history(self, user: str, key: str, before_turn: Optional[int] = None) -> list[LedgerItem]:
        """Items for this key stated before `before_turn` (all of them when None), oldest first."""
        return [i for i in self._by_key.get((user, key), []) if self._before(i.source_turn, before_turn)]

    def current(self, user: str, key: str, before_turn: Optional[int] = None) -> Optional[LedgerItem]:
        """The live value before `before_turn`: the latest item, unless the user asked to forget it."""
        hist = self.history(user, key, before_turn)
        if not hist:
            return None
        last = hist[-1]
        if last.revoked_at_turn is not None and self._before(last.revoked_at_turn, before_turn):
            return None
        return last

    def items_for(self, user: str) -> list[LedgerItem]:
        return [i for i in self.items if i.user_id == user]

    def keys_for(self, user: str) -> list[str]:
        return sorted({k for (u, k) in self._by_key if u == user})

    def to_rows(self) -> list[dict]:
        return [i.to_dict() for i in self.items]

    def _add(self, e: Event, key: str, subject: str, attribute: str, value: str, quote: str, extractor: str):
        live = self.current(e.user_id, key, before_turn=e.index)
        if live is not None and normalize_value(live.value) == normalize_value(value):
            return  # restating the same value is not an update
        item = LedgerItem(f"{e.user_id}:{key}:{e.index}", e.user_id, key, subject, attribute, value, e.index, e.ts,
                          quote, extractor)
        if live is not None:
            live.superseded_by = item.item_id
        self.items.append(item)
        self._by_key[(e.user_id, key)].append(item)
        self.stats["items"] += 1

    def _revoke(self, e: Event, key: str):
        live = self.current(e.user_id, key, before_turn=e.index)
        if live is not None:
            live.revoked_at_turn = e.index


def build_ledger(events: list[Event], judge=None, extractor: Optional[RuleExtractor] = None) -> Ledger:
    """Build the ledger from user turns: rules first, then the LLM extractor for messages worth it."""
    ex = extractor or RuleExtractor()
    if len({e.index for e in events}) < len(events):
        events = [replace(e, index=i) for i, e in enumerate(events)]
    events = sorted(events, key=lambda e: (e.ts, e.index))
    ledger = Ledger({e.index: pos for pos, e in enumerate(events)})
    prompt = load_prompt("extract_facts") if judge is not None else None

    for e in events:
        if e.role != "user":
            continue
        ledger.stats["messages"] += 1
        found: dict[str, dict] = {}  # key -> fact found in this turn
        for attr, value in ex.user_facts(e.content):
            key = normalize_key("user", attr)
            found[key] = {"subject": "user", "attribute": normalize_attribute(attr), "value": value,
                          "quote": sentence(e.content, hint=value), "extractor": "rules"}

        if prompt is not None and worth_extracting(e.content):
            ledger.stats["llm_messages"] += 1
            reply = judge.ask(prompt, role="extractor", as_json=True, message=e.content)
            facts = (reply.data or {}).get("facts") or []
            for f in facts if isinstance(facts, list) else []:
                if not isinstance(f, dict) or not str(f.get("attribute") or "").strip() or not str(f.get("value") or "").strip():
                    ledger.dropped.append({"turn": e.index, "fact": f, "reason": "incomplete"})
                    continue
                span = quote_span(str(f.get("quote") or ""), e.content)
                if span is None:
                    ledger.dropped.append({"turn": e.index, "fact": f, "reason": "quote not in message"})
                    continue
                key = normalize_key(str(f.get("subject") or ""), str(f["attribute"]))
                value = str(f["value"]).strip()
                prior = found.get(key)
                if prior is not None and normalize_value(prior["value"]) == normalize_value(value):
                    prior["extractor"] = "rules+llm"
                    continue
                found[key] = {"subject": normalize_subject(str(f.get("subject") or "")),
                              "attribute": normalize_attribute(str(f["attribute"])), "value": value, "quote": span,
                              "extractor": "llm"}

        for key, f in found.items():
            ledger._add(e, key, f["subject"], f["attribute"], f["value"], f["quote"], f["extractor"])
        for attr in ex.deletions(e.content):
            ledger._revoke(e, normalize_key("user", attr))

    ledger.stats["dropped"] = len(ledger.dropped)
    return ledger
