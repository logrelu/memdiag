"""Detectors that check assistant turns against the fact ledger (docs/plans/M5.md).

They run alongside the legacy rule detectors in detect.py, and run() merges the two sets. Each check is
rules-first: a deterministic candidate filter, then (only with a judge) one specific yes/no question whose
answer must quote the reply verbatim.

    findings, opportunities = detect_with_ledger(events, ledger, judge)
"""
from __future__ import annotations

import re
from typing import Optional

from .detect import DETECTOR_VERSION, _next_user_msg
from .ledger import Ledger, number_and_unit, quote_span, tokens, values_equal
from .prompt import load_prompt
from .schema import Event, Finding
from .text import numbers, sentence

REPAIR = re.compile(
    r"\b(?:as i (?:said|mentioned|told you)|like i (?:said|mentioned|told you)|"
    r"i (?:already |just )?(?:told|said|gave|mentioned) (?:you|that|it|this)|"
    r"did you forget|you forgot|no,? i meant|i said\b[^.?!]*\bnot\b)|\bremember\?", re.I)


# Questions that ask for an attribute, for re-ask detection over any ledger key (not only the legacy four).
REASK_PATTERNS = {
    "age": r"\bhow old\b|\bwhat(?:'s| is) (?:your|his|her|their) age\b",
    "name": r"\bwhat(?:'s| is) (?:your|his|her|their) name\b",
    "birthday": r"\bwhen(?:'s| is) (?:your|his|her|their) birthday\b",
    "interest": r"\bwhat (?:is|are|'s) (?:he|she|they|you) (?:into|interested in)\b|\bwhat does (?:he|she) like\b|"
                r"\bwhat do (?:you|they) like\b",
    "city": r"\bwhere do you live\b|\bwhat city (?:are you in|do you live in)\b|\bwhere are you located\b",
    "employer": r"\bwhere do you work\b|\bwho do you work for\b|\bwho is your employer\b",
    "job_title": r"\bwhat do you do for (?:a living|work)\b|\bwhat(?:'s| is) your (?:job|role|occupation)\b",
    "income": r"\bwhat(?:'s| is) your (?:annual )?(?:income|salary)\b|\bhow much do you (?:make|earn)\b",
    "credit_score": r"\bwhat(?:'s| is) your credit score\b",
}


def _asks_about(sentence_text: str, subject: str, names: list[str]) -> bool:
    """Is a question sentence about this subject: 'you' for the user, the relation or a known name otherwise."""
    words = set(tokens(sentence_text))
    if subject == "user":
        return bool(words & {"you", "your", "yours"})
    return subject.replace("_", " ") in " ".join(tokens(sentence_text)) or any(
        set(tokens(n)) <= words for n in names) or bool(words & {"he", "she", "his", "her", "they", "their"})


def rule_reasks(reply: str, live: dict, ledger: Ledger, user: str, before_turn: int) -> list[tuple[str, str]]:
    """(key, question) pairs where the reply asks again for a live fact, by pattern; no model needed."""
    questions = [q.strip() for q in re.split(r"(?<=[.!?])\s+", reply) if q.strip().endswith("?")]
    people = dict(ledger.known_people(user, before_turn))
    hits = []
    for key in sorted(live):
        subject, _, attribute = key.partition(".")
        pattern = REASK_PATTERNS.get(attribute)
        if not pattern:
            continue
        names = [people[subject]] if subject in people else []
        for q in questions:
            if re.search(pattern, q, re.I) and _asks_about(q, subject, names):
                hits.append((key, q))
                break
    return hits


def mentions(text: str, value: str) -> bool:
    """Does `text` mention `value`? Numbers match by value ($140k == 140000); text as a token sequence."""
    n, _ = number_and_unit(value)
    if n is not None:
        return any(abs(x - abs(n)) < 1e-9 for x in numbers(text))
    want, have = tokens(value), tokens(text)
    if not want:
        return False
    return any(have[i:i + len(want)] == want for i in range(len(have) - len(want) + 1))


def _finding(category: str, a: Event, detector: str, key: str, **kw) -> Finding:
    return Finding(category, a.user_id, a.session_id, a.ts, a.content, failing_turn=a.index, attribute=key,
                   detector=detector, detector_version=DETECTOR_VERSION, **kw)


def detect_with_ledger(events: list[Event], ledger: Ledger, judge=None) -> tuple[list[Finding], dict]:
    """STALE_FACT, RECALL_MISS (judge mode) and USER_REPAIR findings, plus their opportunity counts."""
    events = sorted(events, key=lambda e: (e.ts, e.index))
    stale_prompt = load_prompt("check_stale") if judge is not None else None
    reask_prompt = load_prompt("check_reask") if judge is not None else None
    findings: list[Finding] = []
    opp = {"updated_key_mentions": 0, "live_fact_turns": 0}

    for i, a in enumerate(events):
        if a.role != "assistant":
            continue
        live = {}
        for key in ledger.keys_for(a.user_id):
            cur = ledger.current(a.user_id, key, before_turn=a.index)
            if cur is not None:
                live[key] = cur

        # ---- STALE_FACT: the reply mentions an old value of an updated fact, and not the current one ----
        for key, cur in live.items():
            old = [h for h in ledger.history(a.user_id, key, before_turn=a.index) if not values_equal(h.value, cur.value)]
            if not old:
                continue
            said_old = [h for h in old if mentions(a.content, h.value)]
            said_cur = mentions(a.content, cur.value)
            if not (said_old or said_cur):
                continue
            opp["updated_key_mentions"] += 1
            if not said_old or said_cur:
                continue
            prev = said_old[-1]
            quote, detector, confidence = sentence(a.content, hint=prev.value), "ledger.stale_mention", 0.5
            if judge is not None:
                r = judge.ask(stale_prompt, role="judge_stale", as_json=True, key=key, old=prev.value,
                              old_quote=prev.quote, new=cur.value, new_quote=cur.quote, reply=a.content)
                span = quote_span(str((r.data or {}).get("quote") or ""), a.content)
                if (r.data or {}).get("uses_old") is not True or span is None:
                    continue  # the judge said no, or couldn't point at the words
                quote, detector, confidence = span, "llm.check_stale", 0.9
            findings.append(_finding(
                "stale_memory", a, detector, key, expected=cur.value, got=prev.value, failing_quote=quote,
                evidence_turns=[cur.source_turn, prev.source_turn], evidence_quote=cur.quote, confidence=confidence,
                evidence=f'Updated at turn {cur.source_turn}: "{cur.quote}"',
                covariates={"context_tokens": a.context_tokens}))

        # ---- RECALL_MISS (reask): rule patterns over any live fact, plus the judge for what patterns miss ----
        if live:
            reaskable = live if judge is not None else {k: v for k, v in live.items()
                                                       if k.partition(".")[2] in REASK_PATTERNS}
            if reaskable:
                opp["live_fact_turns"] += 1
            asked: dict[str, tuple[str, str, float]] = {}  # key -> (quote, detector, confidence)
            for key, q in rule_reasks(a.content, reaskable, ledger, a.user_id, a.index):
                asked[key] = (q, "ledger.reask_pattern", 0.6)
            if judge is not None and "?" in a.content:
                facts = "\n".join(f'- {k} = {v.value} (the user said: "{v.quote}")' for k, v in sorted(live.items()))
                r = judge.ask(reask_prompt, role="judge_reask", as_json=True, facts=facts, reply=a.content)
                items = (r.data or {}).get("asks_again") or []
                for item in items if isinstance(items, list) else []:
                    key = str(item.get("key", "")) if isinstance(item, dict) else ""
                    span = quote_span(str(item.get("quote") or ""), a.content) if key in live else None
                    if span is None:
                        continue
                    # The judge can add a re-ask or confirm a rule hit; it can't veto one.
                    asked[key] = (asked[key][0], "ledger.reask_pattern+llm", 0.9) if key in asked else (
                        span, "llm.check_reask", 0.9)
            for key, (quote, detector, confidence) in asked.items():
                cur = live[key]
                findings.append(_finding(
                    "forgotten_memory", a, detector, key, expected=cur.value, got="<asked again>",
                    failing_quote=quote, evidence_turns=[cur.source_turn], evidence_quote=cur.quote,
                    confidence=confidence, evidence=f'Stated at turn {cur.source_turn}: "{cur.quote}"',
                    covariates={"context_tokens": a.context_tokens}))

        # ---- USER_REPAIR: the user's next message repeats or corrects ----
        nxt = _next_user_msg(events, i)
        if nxt is not None and REPAIR.search(nxt.content):
            key = next((k for k, v in sorted(live.items()) if mentions(nxt.content, v.value)), "")
            findings.append(_finding(
                "user_repair", a, "rules.repair_phrase", key, failing_quote=a.content.strip(),
                evidence_turns=[nxt.index], evidence_quote=sentence(nxt.content, pattern=REPAIR.pattern),
                evidence=f'User replied: "{nxt.content}"'))
    return findings, opp


def locate(f: Finding, event: Event, ledger: Ledger) -> Optional[str]:
    """retrieve vs use (L2): was the current value in the memory the agent was given for this call?"""
    if not event.memory or f.category not in ("stale_memory", "forgotten_memory") or not f.attribute:
        return None
    from .ledger import normalize_key
    key = f.attribute if "." in f.attribute else normalize_key("user", f.attribute)
    cur = ledger.current(event.user_id, key, before_turn=event.index)
    if cur is None:
        return None
    memory_text = " ".join(str(m.get("text", "")) for m in event.memory if isinstance(m, dict))
    return "use" if mentions(memory_text, cur.value) else "retrieve"
