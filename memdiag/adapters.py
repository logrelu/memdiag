"""Read the log formats agents already write, and convert them to memdiag Events.

Formats:
  events       memdiag's own JSONL, one message per line (see schema.py)
  openai       one conversation per record: {"messages": [{"role", "content"}], "user_id"?, "session_id"?, "ts"?}
  longmemeval  LongMemEval items: haystack sessions plus the final question

`load(path)` detects the format from the first record. Missing timestamps are filled in order, so turn
order is kept even when a log has no clock.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from .schema import Event

FORMATS = ("auto", "events", "openai", "longmemeval")
_EPOCH = datetime(2000, 1, 1)


def read_records(path) -> list[dict]:
    """A JSON file (one object or a list) or JSONL (one object per line)."""
    with open(path) as f:
        text = f.read()
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]


def detect_format(record: dict) -> str:
    if "haystack_sessions" in record:
        return "longmemeval"
    if "messages" in record:
        return "openai"
    if "role" in record and "user_id" in record:
        return "events"
    raise ValueError("Unrecognized log format: expected memdiag events (user_id, role, content), "
                     "OpenAI-style conversations ({'messages': [...]}) or LongMemEval items. "
                     f"Got keys: {sorted(record)[:8]}")


def _text(content) -> str:
    """Message content as text; OpenAI content can be a list of parts."""
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content or ""


def _ts(value, fallback: datetime) -> datetime:
    return datetime.fromisoformat(value) if value else fallback


def from_events(records: list[dict]) -> list[Event]:
    return [Event.from_dict(d, i) for i, d in enumerate(records)]


def from_openai(records: list[dict]) -> list[Event]:
    events: list[Event] = []
    for c, conv in enumerate(records):
        session = str(conv.get("session_id") or conv.get("id") or f"conv{c}")
        user = str(conv.get("user_id") or session)
        start = _ts(conv.get("ts"), _EPOCH + timedelta(days=c))
        for j, m in enumerate(conv["messages"]):
            if m.get("role") not in ("user", "assistant"):
                continue  # system and tool messages carry no user facts or assistant claims
            events.append(Event(
                user_id=user, session_id=session, ts=_ts(m.get("ts"), start + timedelta(seconds=j)),
                role=m["role"], content=_text(m.get("content")), retrieved=m.get("retrieved") or [],
                context_tokens=m.get("context_tokens"), index=len(events), memory=m.get("memory") or []))
    return events


def _lme_date(s: str) -> datetime:
    """LongMemEval dates look like '2023/05/30 (Tue) 23:51'."""
    return datetime.strptime(re.sub(r"\s*\(\w+\)", "", s).strip(), "%Y/%m/%d %H:%M")


def from_longmemeval(records: list[dict]) -> list[Event]:
    """Each item is one user. Sessions keep their LongMemEval ids, so evidence ids line up."""
    events: list[Event] = []
    for item in records:
        user = str(item["question_id"])
        sessions = zip(item["haystack_session_ids"], item["haystack_dates"], item["haystack_sessions"], strict=True)
        for sid, date, turns in sessions:
            start = _lme_date(date)
            for j, t in enumerate(turns):
                events.append(Event(user, str(sid), start + timedelta(seconds=j), t["role"], t["content"],
                                    index=len(events)))
        events.append(Event(user, "question", _lme_date(item["question_date"]), "user", item["question"],
                            index=len(events)))
    return events


_READERS = {"events": from_events, "openai": from_openai, "longmemeval": from_longmemeval}


def convert(records: list[dict], fmt: str = "auto") -> list[Event]:
    if not records:
        return []
    if fmt == "auto":
        fmt = detect_format(records[0])
    if fmt not in _READERS:
        raise ValueError(f"Unknown format {fmt!r}; choose from {', '.join(FORMATS)}")
    return _READERS[fmt](records)


def load(path, fmt: str = "auto") -> list[Event]:
    return convert(read_records(path), fmt)
