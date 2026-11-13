"""Core data types for memdiag.

Input is a list of trace events (one per message), read from JSONL:

    {"user_id": "u1", "session_id": "s1", "ts": "2026-01-05T10:00:00",
     "role": "user" | "assistant", "content": "...",
     "retrieved": [{"id": "doc_1", "text": "..."}],   # optional, assistant turns: RAG documents
     "memory": [{"id": "m1", "text": "..."}],          # optional, assistant turns: injected memory context
     "context_tokens": 12000}                          # optional, assistant turns

Other log formats are converted to this one by memdiag.adapters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def parse_ts(value: str) -> datetime:
    """ISO timestamp as naive UTC, so logs that mix offset and plain timestamps still sort."""
    ts = datetime.fromisoformat(value)
    return ts.astimezone(timezone.utc).replace(tzinfo=None) if ts.tzinfo else ts

# Failure categories. Each belongs to one class: memory, retrieval or context.
CATEGORIES = {
    "stale_memory": ("memory", "Used an outdated fact after the user updated it"),
    "failed_deletion": ("memory", "Used a fact the user asked it to forget"),
    "cross_user_leak": ("memory", "Used another user's fact"),
    "hallucinated_memory": ("memory", "Claimed to remember a fact the user never stated"),
    "forgotten_memory": ("memory", "Asked again for a fact the user already gave"),
    "retrieval_miss": ("retrieval", "The right document existed but was not retrieved"),
    "ignored_context": ("retrieval", "Retrieved the right document but answered against it"),
    "context_overload": ("context", "Failure happened with a very large context"),
    "unattributed": ("unknown", "User signaled an error that no rule explains"),
}

# Stable Finding type for each legacy category (docs/STABILITY.md), and the mode where one applies.
TYPES = {
    "stale_memory": "STALE_FACT",
    "failed_deletion": "DELETION_VIOLATION",
    "cross_user_leak": "CROSS_USER_LEAK",
    "hallucinated_memory": "HALLUCINATED_MEMORY",
    "forgotten_memory": "RECALL_MISS",
    "retrieval_miss": "RETRIEVAL_MISS",
    "ignored_context": "IGNORED_CONTEXT",
    "context_overload": "CONTEXT_OVERLOAD",
    "unattributed": "UNATTRIBUTED",
}
MODES = {"forgotten_memory": "reask"}


@dataclass
class Event:
    user_id: str
    session_id: str
    ts: datetime
    role: str
    content: str
    retrieved: list = field(default_factory=list)
    context_tokens: Optional[int] = None
    index: int = 0  # position in the trace file
    memory: list = field(default_factory=list)  # memory context injected into this call

    @classmethod
    def from_dict(cls, d: dict, index: int = 0) -> "Event":
        return cls(
            user_id=str(d["user_id"]),
            session_id=str(d.get("session_id", "")),
            ts=parse_ts(d["ts"]),
            role=d["role"],
            content=d.get("content", ""),
            retrieved=d.get("retrieved") or [],
            context_tokens=d.get("context_tokens"),
            index=index,
            memory=d.get("memory") or [],
        )


@dataclass
class Fact:
    """One user-stated fact: (user, attribute) = value at time ts."""
    user_id: str
    attribute: str
    value: Optional[str]  # None means the user asked to delete this attribute
    ts: datetime
    source: str  # the message text it came from
    deleted: bool = False
    index: int = -1  # event index of that message


@dataclass
class Finding:
    category: str
    user_id: str
    session_id: str
    ts: datetime
    turn: str  # the assistant answer
    expected: str = ""
    got: str = ""
    evidence: str = ""
    attribute: str = ""
    user_flagged: bool = False  # the user pushed back right after
    tags: list = field(default_factory=list)
    # Localization: where it failed and the earlier turn(s) it contradicts, with verbatim quotes.
    failing_turn: int = -1
    evidence_turns: list = field(default_factory=list)
    failing_quote: str = ""
    evidence_quote: str = ""
    detector: str = ""
    detector_version: str = ""
    confidence: float = 1.0
    covariates: dict = field(default_factory=dict)

    @property
    def failure_class(self) -> str:
        return CATEGORIES[self.category][0]

    @property
    def type(self) -> str:
        return TYPES[self.category]

    @property
    def mode(self) -> Optional[str]:
        return MODES.get(self.category)

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "class": self.failure_class,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "ts": self.ts.isoformat(),
            "attribute": self.attribute,
            "expected": self.expected,
            "got": self.got,
            "evidence": self.evidence,
            "turn": self.turn,
            "user_flagged": self.user_flagged,
            "tags": self.tags,
            "type": self.type,
            "mode": self.mode,
            "failing_turn": self.failing_turn,
            "evidence_turns": self.evidence_turns,
            "failing_quote": self.failing_quote,
            "evidence_quote": self.evidence_quote,
            "detector": self.detector,
            "detector_version": self.detector_version,
            "confidence": self.confidence,
            "covariates": self.covariates,
        }
