"""Detectors: classify each assistant turn's failures as memory, retrieval or context."""
from __future__ import annotations

import math
from collections import Counter
from typing import Optional

from .extract import FORGOTTEN_QUESTIONS, RuleExtractor, claims, is_complaint, is_unsure, tokens
from dataclasses import replace

from .schema import Event, Finding
from .text import sentence as _sentence
from .timeline import Timeline

CONTEXT_OVERLOAD_TOKENS = 32000
REASKABLE = set(FORGOTTEN_QUESTIONS)  # attributes the rule extractor can spot a re-ask for
DETECTOR_VERSION = "1"  # bump when a rule changes what it flags


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
    if len({e.index for e in events}) < len(events):
        # Events built without explicit indices would all share index 0; number them in input order.
        events = [replace(e, index=i) for i, e in enumerate(events)]
    events = sorted(events, key=lambda e: (e.ts, e.index))
    tl = Timeline(events, ex)
    docs = docs or []
    doc_text = {d["id"]: d["text"] for d in docs}
    bm25 = BM25([d["text"] for d in docs]) if docs else None

    findings: list[Finding] = []
    # Position of each event within its user's own history, for turn distances.
    user_pos: dict[int, int] = {}
    seen: Counter = Counter()
    for ev in events:
        user_pos[ev.index] = seen[ev.user_id]
        seen[ev.user_id] += 1
    assistant_turns = 0
    flagged_turns = 0
    # Denominators for metrics.py: how many times each failure could have happened.
    opp = {"fact_assertions": 0, "update_assertions": 0, "shared_attr_assertions": 0, "known_fact_turns": 0}

    for i, e in enumerate(events):
        if e.role != "assistant":
            continue
        assistant_turns += 1
        nxt = _next_user_msg(events, i)
        flagged = bool(nxt and is_complaint(nxt.content))
        flagged_turns += flagged
        turn_findings: list[Finding] = []

        def add(cat, *, detector, e=e, flagged=flagged, turn_findings=turn_findings,
                fact=None, hint="", pattern="", evidence_turn=None, evidence_quote="", **kw):
            cov = {"context_tokens": e.context_tokens}
            ev_turns = []
            if fact is not None and fact.index >= 0:
                ev_turns = [fact.index]
                evidence_quote = fact.source
                if fact.user_id == e.user_id:  # a distance across two users' histories means nothing
                    cov["turn_distance"] = user_pos[e.index] - user_pos[fact.index]
            elif evidence_turn is not None:
                ev_turns = [evidence_turn]
            turn_findings.append(Finding(
                cat, e.user_id, e.session_id, e.ts, e.content, user_flagged=flagged,
                failing_turn=e.index, evidence_turns=ev_turns, failing_quote=_sentence(e.content, hint, pattern),
                evidence_quote=evidence_quote, detector=f"rules.{detector}", detector_version=DETECTOR_VERSION,
                covariates=cov, **kw))

        # ---- memory: check every fact the agent asserts about this user ----
        for attr, val in ex.assertions(e.content):
            cur = tl.current(e.user_id, attr, e.ts)
            past = tl.past_values(e.user_id, attr, e.ts)
            opp["fact_assertions"] += 1
            opp["update_assertions"] += len(past) >= 2
            opp["shared_attr_assertions"] += tl.other_users_have(e.user_id, attr, e.ts)
            if cur is not None and cur.deleted:
                add("failed_deletion", detector="memory_assertion", fact=cur, hint=val,
                    attribute=attr, expected="<deleted>", got=val,
                    evidence=f'User asked to forget: "{cur.source}"')
            elif cur is not None and cur.value == val:
                continue  # correct, current fact
            elif cur is not None and val in past:
                add("stale_memory", detector="memory_assertion", fact=cur, hint=val,
                    attribute=attr, expected=cur.value, got=val,
                    evidence=f'Updated on {cur.ts.date()}: "{cur.source}"')
            else:
                others = tl.other_users_with(e.user_id, attr, val, e.ts)
                if others:
                    owner = [f for f in tl.history(others[0], attr, e.ts) if f.value == val][-1]
                    add("cross_user_leak", detector="memory_assertion", fact=owner, hint=val,
                        attribute=attr, expected=cur.value if cur else "<unknown>",
                        got=val, evidence=f"Value belongs to user(s): {', '.join(others)}")
                elif cur is None:
                    add("hallucinated_memory", detector="memory_assertion", hint=val,
                        attribute=attr, expected="<never stated>", got=val,
                        evidence="User never stated this attribute")
                else:
                    add("hallucinated_memory", detector="memory_assertion", fact=cur, hint=val,
                        attribute=attr, expected=cur.value, got=val,
                        evidence="Value never stated by any user")

        # ---- memory: asked again for something it was already told ----
        # Every turn where the user had already given a re-askable fact is a chance to re-ask.
        known = tl.known_attrs(e.user_id, e.ts) & REASKABLE
        opp["known_fact_turns"] += bool(known)
        for attr in ex.forgotten_questions(e.content):
            if attr in known:
                cur = tl.current(e.user_id, attr, e.ts)
                add("forgotten_memory", detector="reask", fact=cur, pattern=FORGOTTEN_QUESTIONS[attr],
                    attribute=attr, expected=cur.value, got="<asked again>",
                    evidence=f'Stated on {cur.ts.date()}: "{cur.source}"')

        # ---- retrieval: answer contradicts a retrieved document ----
        answer_claims = claims(e.content)
        retrieved_ids = [r.get("id") for r in e.retrieved]
        for r in e.retrieved:
            text = r.get("text") or doc_text.get(r.get("id"), "")
            for label, dval in claims(text).items():
                aval = answer_claims.get(label)
                if aval and aval != dval:
                    add("ignored_context", detector="document_claims", hint=aval, evidence_quote=text,
                        attribute=label, expected=dval, got=aval,
                        evidence=f'Retrieved {r.get("id")}: "{text}"')

        # ---- retrieval: the right doc existed but was not retrieved ----
        if bm25 and (flagged or is_unsure(e.content)) and not turn_findings:
            q = _prev_user_msg(events, i)
            if q:
                sc = bm25.scores(q.content)
                best = max(range(len(sc)), key=sc.__getitem__)
                if sc[best] > 1.0 and docs[best]["id"] not in retrieved_ids:
                    add("retrieval_miss", detector="bm25_miss", evidence_turn=q.index,
                        evidence_quote=q.content, attribute="document", expected=docs[best]["id"],
                        got=", ".join(retrieved_ids) or "<nothing retrieved>",
                        evidence=f'Best match for "{q.content}": {docs[best]["text"]}')

        # ---- context overload: tag failures that happened with huge context ----
        if (turn_findings or flagged) and (e.context_tokens or 0) >= CONTEXT_OVERLOAD_TOKENS:
            for f in turn_findings:
                f.tags.append(f"context {e.context_tokens:,} tokens")
            add("context_overload", detector="context_size",
                attribute="context", expected=f"< {CONTEXT_OVERLOAD_TOKENS:,} tokens",
                got=f"{e.context_tokens:,} tokens", evidence="Failure occurred with a very large context window")

        # ---- user pushback no rule explains ----
        if flagged and not turn_findings:
            add("unattributed", detector="user_pushback", evidence_turn=nxt.index, evidence_quote=nxt.content,
                evidence=f'User replied: "{nxt.content}"')

        findings.extend(turn_findings)

    opp["deletion_requests"] = tl.deletion_count()
    stats = {"assistant_turns": assistant_turns, "user_flagged_turns": flagged_turns, "opportunities": opp,
             "failed_turns": len({f.failing_turn for f in findings if f.category != "context_overload"})}
    return findings, tl, stats
