"""Rule-based fact extraction (v0).

Extracts user-state facts from user messages and fact *assertions* from
assistant answers, for a fixed set of attributes common in consumer finance
and support agents. The Extractor interface is the seam where an LLM-based
extractor plugs in later; v0 ships only the rule-based one.
"""
from __future__ import annotations

import re
from typing import Iterable

NAME = r"([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?)"
ORG = r"([A-Z][\w&\.]+(?:\s[A-Z][\w&\.]+)?)"
MONEY = r"\$?\s?([\d][\d,]*(?:\.\d+)?\s?[kK]?)"

LOANS = r"(car loan|student loan|mortgage|personal loan)"

# --- user statements: (attribute, regex, value transform) -------------------
USER_PATTERNS = [
    ("city", rf"\b(?i:I live in|I'm based in|I am based in|I(?: just)? moved to|we(?: just)? moved to|I relocated to|I now live in|I'm now in)\s+{NAME}", None),
    ("employer", rf"\b(?i:I work at|I work for|I started a new job at|I started at|I(?: just)? joined|my new job is at)\s+{ORG}", None),
    ("income", rf"\b(?i:I make|I earn|I now make|my income is(?: now)?|my salary is(?: now)?|my salary went up to)\s+{MONEY}", "money"),
    ("credit_score", r"(?i:\bmy (?:credit )?score is(?: now)?)\s+(\d{3})", None),
]
USER_LOAN_OPEN = rf"\bI (?:have|still have|took out|just took out) (?:a |an |my )?{LOANS}"
USER_LOAN_PAID = rf"\bI (?:just |finally |also )*paid off my {LOANS}"

DELETE_WORDS = r"\b(?:please )?(?:forget|delete|remove|stop using|don't (?:store|keep|remember))\b"
DELETE_TARGETS = {
    "income": r"income|salary|how much I make",
    "employer": r"employer|job|where I work",
    "city": r"address|location|city|where I live",
    "credit_score": r"credit score|score",
}

# --- assistant assertions ----------------------------------------------------
ASSIST_PATTERNS = [
    ("city", rf"\b(?i:you live in|you're in|you are in|you're based in|you are based in|near you in|since you(?:'re| are) in|since you live in)\s+{NAME}", None),
    ("employer", rf"\b(?i:you work at|you work for|your job at|your role at|since you work at|since you're at)\s+{ORG}", None),
    ("income", rf"\b(?i:your income of|your salary of|you make|you earn|an income of)\s+{MONEY}", "money"),
    ("income", rf"(?i:\byour) {MONEY} (?i:income|salary)", "money"),
    ("credit_score", r"(?i:\b(?:your (?:credit )?score of|with (?:a|your) ))(\d{3})(?i:(?: credit)? score)", None),
]
ASSIST_LOAN_OPEN = rf"\byour {LOANS}(?:'s)?\s+(?:balance|payment|payments|first)"

FORGOTTEN_QUESTIONS = {
    "city": r"\b(where do you live|what city (?:are you in|do you live in)|where are you located)\b",
    "employer": r"\b(where do you work|who do you work for|who is your employer)\b",
    "income": r"\b(what(?:'s| is) your (?:annual )?(?:income|salary)|how much do you (?:make|earn))\b",
    "credit_score": r"\b(what(?:'s| is) your credit score)\b",
}

COMPLAINT = re.compile(
    r"\b(that's wrong|that is wrong|that's not right|not anymore|i told you|i already told you|"
    r"i already said|i asked you to forget|i don't work there|i paid that off|that's not me|"
    r"that isn't mine|not helpful|that's not my)\b",
    re.I,
)
UNSURE = re.compile(r"\b(I'm not sure|I don't have (?:that |any )?information|I couldn't find)\b", re.I)


def norm_money(v: str) -> str:
    v = v.replace("$", "").replace(",", "").replace(" ", "").lower()
    mult = 1000 if v.endswith("k") else 1
    v = v.rstrip("k")
    try:
        return str(int(float(v) * mult))
    except ValueError:
        return v


def _clean(v: str, kind) -> str:
    v = v.strip().rstrip(".,;!")
    return norm_money(v) if kind == "money" else v


class RuleExtractor:
    """Extract facts with regexes. Swap for an LLM extractor in production."""

    def user_facts(self, text: str) -> list[tuple[str, str]]:
        out = []
        for attr, pat, kind in USER_PATTERNS:
            for m in re.finditer(pat, text):
                out.append((attr, _clean(m.group(1), kind)))
        for m in re.finditer(USER_LOAN_OPEN, text, re.I):
            out.append(("loan:" + m.group(1).lower(), "open"))
        for m in re.finditer(USER_LOAN_PAID, text, re.I):
            out.append(("loan:" + m.group(1).lower(), "paid_off"))
        return out

    def deletions(self, text: str) -> list[str]:
        if not re.search(DELETE_WORDS, text, re.I):
            return []
        attrs = []
        for attr, pat in DELETE_TARGETS.items():
            if re.search(rf"{DELETE_WORDS}[^.?!]*\b(?:{pat})\b", text, re.I):
                attrs.append(attr)
        return attrs

    def assertions(self, text: str) -> list[tuple[str, str]]:
        out = []
        for attr, pat, kind in ASSIST_PATTERNS:
            for m in re.finditer(pat, text):
                out.append((attr, _clean(m.group(1), kind)))
        for m in re.finditer(ASSIST_LOAN_OPEN, text, re.I):
            out.append(("loan:" + m.group(1).lower(), "open"))
        return out

    def forgotten_questions(self, text: str) -> list[str]:
        return [a for a, pat in FORGOTTEN_QUESTIONS.items() if re.search(pat, text, re.I)]


def is_complaint(text: str) -> bool:
    return bool(COMPLAINT.search(text))


def is_unsure(text: str) -> bool:
    return bool(UNSURE.search(text))


# --- document claims: "<label> ... <value>" pairs, e.g. "APR of 21.49%" ------
CLAIM = re.compile(
    r"\b(APR|APY|annual fee|late (?:payment )?fee|fee|rate|credit limit|minimum payment)\b[^\d$.]{0,25}(\$?\d[\d,]*(?:\.\d+)?%?)",
    re.I,
)


def claims(text: str) -> dict[str, str]:
    """Map normalized label -> value for numeric claims in a text."""
    out = {}
    for m in CLAIM.finditer(text):
        label = m.group(1).lower()
        label = "late fee" if label.startswith("late") else label
        out.setdefault(label, m.group(2).replace(",", ""))
    return out


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def iter_values(facts: Iterable) -> set:
    return {f.value for f in facts if f.value is not None}
