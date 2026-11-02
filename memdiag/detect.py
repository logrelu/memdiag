"""Detectors: classify each assistant turn's failures as memory, retrieval or context."""
from __future__ import annotations

import math
from collections import Counter
from typing import Optional

from .extract import RuleExtractor, claims, is_complaint, is_unsure, tokens
from .schema import Event, Finding
from .timeline import Timeline

CONTEXT_OVERLOAD_TOKENS = 32000


class BM25:
    """Tiny BM25 so memdiag has no dependencies."""

    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.toks = [tokens(d) for d in docs]
        self.k1, self.b = k1, b
        self.avg = sum(map(len, self.toks)) / max(len(self.toks), 1)
        df = Counter(t for d in self.toks for t in set(d))
        n = len(self.toks)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scores(self, query: str) -> list[float]:
        q = tokens(query)
        out = []
        for d in self.toks:
            tf = Counter(d)
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self.idf.get(t, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(d) / self.avg))
            out.append(s)
        return out


def _next_user_msg(events: list[Event], i: int) -> Optional[Event]:
    a = events[i]
    for e in events[i + 1:]:
        if e.user_id != a.user_id or e.session_id != a.session_id:
            continue
        if e.role == "user":
            return e
        if e.role == "assistant":
            return None
    return None


def _prev_user_msg(events: list[Event], i: int) -> Optional[Event]:
    a = events[i]
    for e in reversed(events[:i]):
        if e.user_id == a.user_id and e.session_id == a.session_id and e.role == "user":
            return e
    return None


def diagnose(events: list[Event], docs: Optional[list[dict]] = None,
             extractor: Optional[RuleExtractor] = None) -> tuple[list[Finding], Timeline, dict]:
    ex = extractor or RuleExtractor()
    events = sorted(events, key=lambda e: (e.ts, e.index))
    tl = Timeline(events, ex)
    docs = docs or []
    doc_text = {d["id"]: d["text"] for d in docs}
    bm25 = BM25([d["text"] for d in docs]) if docs else None

    findings: list[Finding] = []
    assistant_turns = 0
    flagged_turns = 0

    for i, e in enumerate(events):
        if e.role != "assistant":
            continue
        assistant_turns += 1
        nxt = _next_user_msg(events, i)
        flagged = bool(nxt and is_complaint(nxt.content))
        flagged_turns += flagged
        turn_findings: list[Finding] = []

        def add(cat, **kw):
            turn_findings.append(Finding(cat, e.user_id, e.session_id, e.ts, e.content,
                                         user_flagged=flagged, **kw))

        # ---- memory: check every fact the agent asserts about this user ----
        for attr, val in ex.assertions(e.content):
            cur = tl.current(e.user_id, attr, e.ts)
            past = tl.past_values(e.user_id, attr, e.ts)
            if cur is not None and cur.deleted:
                add("failed_deletion", attribute=attr, expected="<deleted>", got=val,
                    evidence=f'User asked to forget: "{cur.source}"')
            elif cur is not None and cur.value == val:
                continue  # correct, current fact
            elif cur is not None and val in past:
                add("stale_memory", attribute=attr, expected=cur.value, got=val,
                    evidence=f'Updated on {cur.ts.date()}: "{cur.source}"')
            else:
                others = tl.other_users_with(e.user_id, attr, val, e.ts)
                if others:
                    add("cross_user_leak", attribute=attr, expected=cur.value if cur else "<unknown>",
                        got=val, evidence=f"Value belongs to user(s): {', '.join(others)}")
                elif cur is None:
                    add("hallucinated_memory", attribute=attr, expected="<never stated>", got=val,
                        evidence="User never stated this attribute")
                else:
                    add("hallucinated_memory", attribute=attr, expected=cur.value, got=val,
                        evidence="Value never stated by any user")

        # ---- memory: asked again for something it was already told ----
        for attr in ex.forgotten_questions(e.content):
            cur = tl.current(e.user_id, attr, e.ts)
            if cur is not None and not cur.deleted:
                add("forgotten_memory", attribute=attr, expected=cur.value, got="<asked again>",
                    evidence=f'Stated on {cur.ts.date()}: "{cur.source}"')

        # ---- retrieval: answer contradicts a retrieved document ----
        answer_claims = claims(e.content)
        retrieved_ids = [r.get("id") for r in e.retrieved]
        for r in e.retrieved:
            text = r.get("text") or doc_text.get(r.get("id"), "")
            for label, dval in claims(text).items():
                aval = answer_claims.get(label)
                if aval and aval != dval:
                    add("ignored_context", attribute=label, expected=dval, got=aval,
                        evidence=f'Retrieved {r.get("id")}: "{text}"')

        # ---- retrieval: the right doc existed but was not retrieved ----
        if bm25 and (flagged or is_unsure(e.content)) and not turn_findings:
            q = _prev_user_msg(events, i)
            if q:
                sc = bm25.scores(q.content)
                best = max(range(len(sc)), key=sc.__getitem__)
                if sc[best] > 1.0 and docs[best]["id"] not in retrieved_ids:
                    add("retrieval_miss", attribute="document", expected=docs[best]["id"],
                        got=", ".join(retrieved_ids) or "<nothing retrieved>",
                        evidence=f'Best match for "{q.content}": {docs[best]["text"]}')

        # ---- context overload: tag failures that happened with huge context ----
        if (turn_findings or flagged) and (e.context_tokens or 0) >= CONTEXT_OVERLOAD_TOKENS:
            for f in turn_findings:
                f.tags.append(f"context {e.context_tokens:,} tokens")
            add("context_overload", attribute="context", expected=f"< {CONTEXT_OVERLOAD_TOKENS:,} tokens",
                got=f"{e.context_tokens:,} tokens", evidence="Failure occurred with a very large context window")

        # ---- user pushback no rule explains ----
        if flagged and not turn_findings:
            add("unattributed", evidence=f'User replied: "{nxt.content}"')

        findings.extend(turn_findings)

    stats = {"assistant_turns": assistant_turns, "user_flagged_turns": flagged_turns,
             "failed_turns": len({(f.user_id, f.session_id, f.ts) for f in findings if f.category != "context_overload"})}
    return findings, tl, stats
