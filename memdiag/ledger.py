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
FILLER = {"my", "our", "the", "a", "an", "of"}
PRONOUNS = {"he", "she", "they", "him", "her", "his", "their", "them", "it", "its"}
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
ATTRIBUTE_NAMES = set(ATTRIBUTE_SYNONYMS) | set(_SYNONYM) - {"name"}


def tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if t]


def normalize_subject(subject: str) -> str:
    """'I', 'user|myself', '' -> 'user'; 'my daughter' -> 'daughter'; 'user|Maya' -> 'maya'.

    A bare pronoun ('she', 'his') names nobody we can key on, so it returns '' and the fact is dropped.
    'his manager' and 'her manager' stay distinct.
    """
    rest = [t for t in tokens(subject) if t not in SELF and t not in FILLER]
    if len(rest) == 1 and rest[0] in PRONOUNS:
        return ""
    return "_".join(rest) or "user"


def normalize_attribute(attribute: str) -> str:
    """Lowercase snake_case with synonyms folded: 'Home City' -> 'city', 'loan:car loan' -> 'loan_car_loan'."""
    toks = tokens(attribute)
    while toks and toks[0] in SELF | FILLER:
        toks = toks[1:]
    name = "_".join(toks)
    return _SYNONYM.get(name, name)


def normalize_key(subject: str, attribute: str) -> str:
    return f"{normalize_subject(subject)}.{normalize_attribute(attribute)}"


_NUMBER = r"(\d[\d,]*(?:\.\d+)?)\s*[kKmM]?\b"


def number_and_unit(value) -> tuple[Optional[float], str]:
    """'-$1.5k' -> (-1500.0, ''); '4.10%' -> (4.1, ''); '7 years' -> (7.0, 'years'); 'Denver' -> (None, 'denver')."""
    text = str(value or "")
    nums = numbers(text)
    if len(nums) != 1:
        return None, " ".join(tokens(text))
    sign = -1 if re.search(r"(?<![\w.])-\s*[$€£]?\s*\d", text) else 1
    unit = " ".join(tokens(re.sub(_NUMBER + r"|[$€£%,\-]", " ", text)))
    return sign * nums[0], unit


def normalize_value(value) -> str:
    """Canonical text for a value: '$140k' -> '140000', '4.10%' -> '4.1', 'Denver.' -> 'denver'."""
    n, unit = number_and_unit(value)
    if n is None:
        return unit
    num = str(int(n)) if n == int(n) else str(n)
    return f"{num} {unit}".strip()


def values_equal(a, b) -> bool:
    """Same value stated two ways: '$140k' == '140000', '7 years' == '7', but '-5' != '5', '7 years' != '7 months'."""
    (na, ua), (nb, ub) = number_and_unit(a), number_and_unit(b)
    if na is None or nb is None:
        return normalize_value(a) == normalize_value(b)
    return na == nb and (ua == ub or not ua or not ub)


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


# Personal statements are in the first person, or about people in the user's life ("she's 7 now").
PERSONAL = re.compile(r"\b(i|i'm|im|i've|i'd|my|me|mine|we|we're|we've|our|us|"
                      r"he|she|he's|she's|his|her|they|they're|their)\b", re.I)


def worth_extracting(text: str) -> bool:
    """Cheap filter before any LLM call: a personal statement that isn't only questions."""
    if not PERSONAL.search(text):
        return False
    parts = [p for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]
    return any(not p.rstrip().endswith("?") for p in parts)


def without_code(text: str) -> str:
    """Drop fenced code blocks: pasted code carries no facts about the user, only cost."""
    return re.sub(r"```.*?(```|$)", " ", text, flags=re.S)


QUOTE_MARKS = "\"'“”‘’«»`"


def quote_span(quote: str, text: str) -> Optional[str]:
    """The exact span of `text` that `quote` matches, ignoring case, runs of whitespace and one pair of
    quotation marks a model wrapped around it; None if absent. Matches whole words only ("hi" is not in "this").
    """
    q = (quote or "").strip()
    if len(q) >= 2 and q[0] in QUOTE_MARKS and q[-1] in QUOTE_MARKS:
        q = q[1:-1].strip()
    words = q.split()
    if not words:
        return None
    pattern = r"\s+".join(map(re.escape, words))
    if re.match(r"\w", words[0]):
        pattern = r"(?<!\w)" + pattern
    if re.search(r"\w$", words[-1]):
        pattern += r"(?!\w)"
    m = re.search(pattern, text, re.I)
    return m.group(0) if m else None


class Ledger:
    def __init__(self, order: dict[int, int]):
        self.items: list[LedgerItem] = []
        self.dropped: list[dict] = []  # facts rejected or overridden, with the reason, for audit
        self.stats = {"messages": 0, "llm_messages": 0, "items": 0, "dropped": 0}
        self._order = order  # event index -> position in time order
        self._by_key: dict[tuple, list[LedgerItem]] = defaultdict(list)

    def _before(self, item_turn: int, turn: Optional[int]) -> bool:
        if turn is None:
            return True
        if turn not in self._order:
            raise ValueError(f"turn {turn} is not in this log (turns are event indices 0..{len(self._order) - 1})")
        return self._order[item_turn] < self._order[turn]

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

    def known_people(self, user: str, before_turn: Optional[int] = None) -> list[tuple[str, str]]:
        """(relation, name) for people in the user's life with a live name, e.g. ("daughter", "Maya")."""
        out = []
        for (u, key) in self._by_key:
            subject, _, attribute = key.partition(".")
            if u == user and subject != "user" and attribute == "name":
                item = self.current(user, key, before_turn)
                if item is not None:
                    out.append((subject, item.value))
        return sorted(out)

    def keys_for(self, user: str) -> list[str]:
        return sorted({k for (u, k) in self._by_key if u == user})

    def to_rows(self) -> list[dict]:
        return [i.to_dict() for i in self.items]

    def _add(self, e: Event, key: str, subject: str, attribute: str, value: str, quote: str, extractor: str):
        live = self.current(e.user_id, key, before_turn=e.index)
        if live is not None and values_equal(live.value, value):
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

        def drop(fact, reason, e=e):
            ledger.dropped.append({"turn": e.index, "fact": fact, "reason": reason})

        for attr, value in ex.user_facts(e.content):
            key = normalize_key("user", attr)
            if key in found:  # the same message states it twice; the later statement wins
                drop(found[key], "restated later in the same message")
            found[key] = {"subject": "user", "attribute": normalize_attribute(attr), "value": value,
                          "quote": sentence(e.content, hint=value), "extractor": "rules"}

        text = without_code(e.content)
        if prompt is not None and worth_extracting(text):
            ledger.stats["llm_messages"] += 1
            people = ledger.known_people(e.user_id, before_turn=e.index)
            known = "\n".join(f"- {rel}: {name}" for rel, name in people) or "- (none yet)"
            reply = judge.ask(prompt, role="extractor", as_json=True, message=text, known_people=known)
            facts = (reply.data or {}).get("facts") or []
            for f in facts if isinstance(facts, list) else []:
                if not isinstance(f, dict):
                    drop(f, "incomplete")
                    continue
                subject = normalize_subject(str(f.get("subject") or ""))
                attribute = normalize_attribute(str(f.get("attribute") or ""))
                value = str(f.get("value") or "").strip()
                if not subject or not attribute or not value:
                    drop(f, "incomplete" if subject else "subject is only a pronoun")
                    continue
                if subject in ATTRIBUTE_NAMES:  # e.g. subject "job_title": the model swapped the fields
                    drop(f, f"subject {subject!r} is an attribute name")
                    continue
                span = quote_span(str(f.get("quote") or ""), e.content)
                if span is None:
                    drop(f, "quote not in message")
                    continue
                key = f"{subject}.{attribute}"
                prior = found.get(key)
                if prior is not None:
                    if values_equal(prior["value"], value):
                        prior["extractor"] = "rules+llm"
                    else:  # rules are precise where they fire; keep them and record the disagreement
                        drop(f, f"conflicts with rule fact {prior['value']!r} in the same message")
                    continue
                found[key] = {"subject": subject, "attribute": attribute, "value": value, "quote": span,
                              "extractor": "llm"}

        for key, f in found.items():
            ledger._add(e, key, f["subject"], f["attribute"], f["value"], f["quote"], f["extractor"])
        for attr in ex.deletions(e.content):
            ledger._revoke(e, normalize_key("user", attr))

    ledger.stats["dropped"] = len(ledger.dropped)
    return ledger
