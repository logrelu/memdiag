"""Core data types for memdiag.

Input is a list of trace events (one per message), read from JSONL:

    {"user_id": "u1", "session_id": "s1", "ts": "2026-01-05T10:00:00",
     "role": "user" | "assistant", "content": "...",
     "retrieved": [{"id": "doc_1", "text": "..."}],   # optional, assistant turns
     "context_tokens": 12000}                          # optional, assistant turns
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

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

    @classmethod
    def from_dict(cls, d: dict, index: int = 0) -> "Event":
        return cls(
            user_id=str(d["user_id"]),
            session_id=str(d.get("session_id", "")),
            ts=datetime.fromisoformat(d["ts"]),
            role=d["role"],
            content=d.get("content", ""),
            retrieved=d.get("retrieved") or [],
            context_tokens=d.get("context_tokens"),
            index=index,
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

    @property
    def failure_class(self) -> str:
        return CATEGORIES[self.category][0]

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
        }
