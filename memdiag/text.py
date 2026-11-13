"""Small text helpers shared by detectors and the ledger. Quotes they return are verbatim substrings."""
from __future__ import annotations

import re
from typing import Optional


def sentence(text: str, hint: str = "", pattern: str = "") -> str:
    """The sentence of `text` that contains `hint` (or matches `pattern`); the whole text if none does.

    Always a verbatim substring of `text`, so it can be quoted as evidence.
    """
    parts = [p for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    for p in parts:
        if (pattern and re.search(pattern, p, re.I)) or (hint and hint.lower() in p.lower()):
            return p.strip()
    # Numeric values are normalized ("$140k" asserted as "140000"): match the same number, not a prefix.
    target = number(hint)
    if target is not None:
        for p in parts:
            if target in numbers(p):
                return p.strip()
    return text.strip()


def number(s: str) -> Optional[float]:
    found = numbers(s)
    return found[0] if len(found) == 1 else None


def numbers(s: str) -> list[float]:
    out = []
    for num, suffix in re.findall(r"(\d[\d,]*(?:\.\d+)?)\s*([kKmM]?)\b", s):
        v = float(num.replace(",", ""))
        out.append(v * {"k": 1e3, "m": 1e6}.get(suffix.lower(), 1))
    return out
