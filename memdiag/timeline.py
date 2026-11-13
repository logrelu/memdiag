"""Per-user timeline of stated facts, with updates and deletions."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Optional

from .extract import RuleExtractor
from .schema import Event, Fact


class Timeline:
    def __init__(self, events: list[Event], extractor: Optional[RuleExtractor] = None):
        self.extractor = extractor or RuleExtractor()
        # (user, attribute) -> ordered list of Facts (value None = deletion)
        self.facts: dict[tuple, list[Fact]] = defaultdict(list)
        for e in sorted(events, key=lambda x: (x.ts, x.index)):
            if e.role != "user":
                continue
            for attr, val in self.extractor.user_facts(e.content):
                self.facts[(e.user_id, attr)].append(Fact(e.user_id, attr, val, e.ts, e.content))
            for attr in self.extractor.deletions(e.content):
                self.facts[(e.user_id, attr)].append(Fact(e.user_id, attr, None, e.ts, e.content, deleted=True))

    def history(self, user: str, attr: str, before: datetime) -> list[Fact]:
        return [f for f in self.facts.get((user, attr), []) if f.ts < before]

    def current(self, user: str, attr: str, at: datetime) -> Optional[Fact]:
        """Latest fact (or deletion) for this attribute before time `at`."""
        h = self.history(user, attr, at)
        return h[-1] if h else None

    def past_values(self, user: str, attr: str, at: datetime) -> set:
        return {f.value for f in self.history(user, attr, at) if f.value is not None}

    def other_users_with(self, user: str, attr: str, value: str, at: datetime) -> list[str]:
        return sorted({
            u for (u, a), fs in self.facts.items()
            if a == attr and u != user and any(f.value == value and f.ts < at for f in fs)
        })

    def other_users_have(self, user: str, attr: str, at: datetime) -> bool:
        """True if some other user has stated a value for this attribute before `at`."""
        return any(a == attr and u != user and any(f.ts < at and f.value is not None for f in fs)
                   for (u, a), fs in self.facts.items())

    def known_attrs(self, user: str, at: datetime) -> set:
        """Attributes the user has stated before `at` and not asked to forget."""
        return {a for (u, a) in self.facts if u == user
                and (cur := self.current(user, a, at)) is not None and not cur.deleted}

    def deletion_count(self) -> int:
        """Number of deletion requests (one per user and attribute, counting each request)."""
        return sum(f.deleted for fs in self.facts.values() for f in fs)

    def users(self) -> list[str]:
        return sorted({u for (u, _) in self.facts})

    def to_rows(self) -> list[dict]:
        rows = []
        for (u, a), fs in sorted(self.facts.items()):
            for f in fs:
                rows.append({"user_id": u, "attribute": a, "value": f.value if not f.deleted else "<deleted>",
                             "ts": f.ts.isoformat(), "source": f.source})
        return rows
