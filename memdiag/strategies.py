"""Replay user history through candidate memory strategies, offline.

For every point where the agent needed a user fact (it asserted one, or asked
for one), each strategy is asked what it would have recalled. That answer is
compared with the user's true current state from the timeline.

This answers "which memory approach fits our traffic?" in minutes, before
integrating any vendor. Real backends (Zep, Mem0, a graph store) plug in by
implementing MemoryBackend and replaying the same history.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .detect import BM25
from .extract import RuleExtractor
from .schema import Event
from .timeline import Timeline

ATTR_QUERY = {
    "city": "live moved city based relocated location",
    "employer": "work job joined employer started",
    "income": "income salary make earn",
    "credit_score": "credit score",
}


class MemoryBackend(Protocol):
    """Interface for plugging a real memory system into the replay."""

    def add(self, user_id: str, text: str, ts) -> None: ...
    def recall(self, user_id: str, attribute: str) -> set: ...


@dataclass
class Probe:
    user_id: str
    attribute: str
    ts: object
    expected: set  # empty set = nothing should be recalled


def build_probes(events: list[Event], tl: Timeline, ex: RuleExtractor) -> list[Probe]:
    probes, seen = [], set()
    for e in events:
        if e.role != "assistant":
            continue
        attrs = [a for a, _ in ex.assertions(e.content)] + ex.forgotten_questions(e.content)
        for a in attrs:
            key = (e.user_id, a, e.ts)
            if key in seen:
                continue
            seen.add(key)
            cur = tl.current(e.user_id, a, e.ts)
            exp = set() if cur is None or cur.deleted else {cur.value}
            probes.append(Probe(e.user_id, a, e.ts, exp))
    return probes


class _Base:
    name = ""
    description = ""

    def __init__(self, events: list[Event], ex: RuleExtractor):
        self.events = [e for e in events if e.role == "user"]
        self.ex = ex

    def _msgs(self, user, ts, scoped=True):
        return [e for e in self.events if e.ts < ts and (e.user_id == user or not scoped)]

    def _values(self, msgs, attr):
        return {v for m in msgs for a, v in self.ex.user_facts(m.content) if a == attr}

    def tokens(self, user, ts) -> int:
        return 0


class NoMemory(_Base):
    name, description = "No memory", "Agent sees only the current session"

    def recall(self, user, attr, ts):
        return set()


class FullHistory(_Base):
    name, description = "Full history in context", "All past messages stuffed into the prompt"

    def recall(self, user, attr, ts):
        return self._values(self._msgs(user, ts), attr)

    def tokens(self, user, ts):
        return sum(len(m.content) for m in self._msgs(user, ts)) // 4


class TopK(_Base):
    k = 2
    scoped = True
    name, description = "Top-k search, per user", "Similarity search over each user's past messages"

    def recall(self, user, attr, ts):
        msgs = self._msgs(user, ts, scoped=self.scoped)
        if not msgs:
            return set()
        sc = BM25([m.content for m in msgs]).scores(ATTR_QUERY.get(attr, attr.replace("loan:", "") + " loan paid"))
        top = sorted(range(len(msgs)), key=lambda i: -sc[i])[: self.k]
        return self._values([msgs[i] for i in top if sc[i] > 0], attr)

    def tokens(self, user, ts):
        return 60 * self.k


class TopKShared(TopK):
    scoped = False
    name, description = "Top-k search, shared index", "One index across all users (no per-user scoping)"


class ProfileLatest(_Base):
    honors_deletion = False
    name, description = "Profile, latest value wins", "Key-value profile, overwrite on update, ignores deletion requests"

    def recall(self, user, attr, ts):
        val = None
        for m in self._msgs(user, ts):
            for a, v in self.ex.user_facts(m.content):
                if a == attr:
                    val = v
            if self.honors_deletion and attr in self.ex.deletions(m.content):
                val = None
        return {val} if val else set()

    def tokens(self, user, ts):
        return 40


class ProfileWithForget(ProfileLatest):
    honors_deletion = True
    name, description = "Profile + deletion", "Key-value profile that also honors 'forget my X' requests"


STRATEGIES = [NoMemory, FullHistory, TopK, TopKShared, ProfileLatest, ProfileWithForget]


def compare(events: list[Event], tl: Timeline, ex: RuleExtractor) -> tuple[list[dict], list[Probe]]:
    probes = build_probes(sorted(events, key=lambda e: (e.ts, e.index)), tl, ex)
    rows = []
    for cls in STRATEGIES:
        s = cls(events, ex)
        r = {"strategy": s.name, "description": s.description, "probes": len(probes),
             "correct": 0, "missing": 0, "stale": 0, "deleted_exposed": 0, "cross_user": 0, "tokens": 0}
        for p in probes:
            got = s.recall(p.user_id, p.attribute, p.ts)
            r["tokens"] += s.tokens(p.user_id, p.ts)
            if got == p.expected:
                r["correct"] += 1
                continue
            past = tl.past_values(p.user_id, p.attribute, p.ts)
            cur = tl.current(p.user_id, p.attribute, p.ts)
            if not got:
                r["missing"] += 1
            elif cur is not None and cur.deleted:
                r["deleted_exposed"] += 1
            elif got - past:
                r["cross_user"] += 1
            else:
                r["stale"] += 1
        r["accuracy"] = r["correct"] / len(probes) if probes else 0.0
        r["avg_tokens"] = r["tokens"] // max(len(probes), 1)
        rows.append(r)
    return rows, probes
