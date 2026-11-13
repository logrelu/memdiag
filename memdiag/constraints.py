"""Instructions the user gives about replies, and whether later replies keep them (CONSTRAINT_DROP).

Only mechanically checkable kinds are covered, so no model is needed and every verdict is exact:
max_words, max_sentences, language, bullets, no_bullets, json_only, banned_word, no_emoji, lowercase.

A constraint holds for later assistant turns in the same session until the user revokes it or replaces it
with a newer one of the same kind. A turn is skipped (no opportunity, no failure) when the user's message
right before it asks for something that conflicts with the constraint, or when a reply is too short to check.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

from .schema import Event, Finding
from .text import sentence

NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "nine": 9, "ten": 10}
LANGUAGES = {"english": "en", "spanish": "es", "french": "fr", "german": "de", "italian": "it", "portuguese": "pt"}
LANGUAGE_NAMES = {v: k.capitalize() for k, v in LANGUAGES.items()}
STOPWORDS = {
    "en": {"the", "and", "is", "you", "to", "of", "a", "in", "that", "it", "for", "with", "are", "this", "be", "on", "when"},
    "es": {"el", "la", "de", "que", "y", "en", "los", "es", "por", "para", "con", "una", "un", "las", "del", "cuando", "hace"},
    "fr": {"le", "la", "les", "de", "et", "est", "vous", "que", "une", "un", "des", "pour", "dans", "pas", "il", "nous"},
    "de": {"der", "die", "das", "und", "ist", "nicht", "sie", "ich", "mit", "ein", "eine", "zu", "auf", "den", "es", "kann"},
    "it": {"il", "di", "che", "e", "la", "per", "non", "una", "sono", "con", "gli", "del", "un", "è"},
    "pt": {"o", "a", "de", "que", "e", "do", "da", "em", "um", "para", "com", "não", "uma", "os", "é"},
}

# A standing instruction is purely about replies. It either signals persistence ("from now on", "your
# answers"), or nothing is left once the instruction is removed ("No emojis please."). "No emojis in my
# wedding invite" or "Write an essay under 500 words" is a one-off task, not an instruction for later replies.
PERSIST = (r"\b(?:from now on|going forward|for the rest of (?:this|the) (?:chat|conversation)|in this (?:chat|conversation)|"
           r"always|(?:your|all|the) (?:answers?|replies|responses)|keep (?:it|them|things|your \w+))\b")
TASK_OBJECT = r"\b(?:in|for|on|to|of|about) (?:my|the|this|that|our|his|her|their|a|an) (?!(?:chat|conversation)\b)[a-z]+"
BARE = {"please", "reply", "replies", "respond", "responses", "response", "answer", "answers", "write", "back", "use",
        "using", "only", "me", "to", "and", "from", "now", "on", "keep", "it", "them", "your", "in", "just", "always",
        "actually", "also", "ok", "okay", "but", "the", "all", "never", "don't", "dont", "do", "not", "stop", "no",
        "any", "with", "going", "forward", "talk", "speak", "be", "sure"}
LANG = "(" + "|".join(LANGUAGES) + ")"
EXTRACT = [
    ("max_words", r"\b(?:under|below|less than|fewer than|no more than|at most|max(?:imum)?(?: of)?|within)\s+(\d+)\s+words\b|"
                  r"\bin\s+(\d+)\s+words or (?:less|fewer)\b"),
    ("max_sentences", r"\b(?:in|to|with|using)\s+(one|two|three|four|five|\d+)\s+sentences?\b"),
    ("language", rf"\b(?:in|only in)\s+{LANG}\b"),
    ("no_bullets", r"\b(?:don't|do not|no|never|stop using|avoid)\s+(?:use\s+|using\s+)?(?:any\s+)?(?:bullet points|bullets|bulleted lists?)\b"),
    # An imperative at the start of the sentence ("Use bullet points"), not a statement ("we use bullet points").
    ("bullets", r"^\s*(?:please\s+|always\s+|and\s+)?use (?:bullet points|bullets|a bulleted list)\b|"
                r"\b(?:answer|reply|respond|list (?:them|it|things))\b[^.?!]*\b(?:as|in|with) (?:a )?(?:bulleted list|bullet points|bullets)\b"),
    ("json_only", r"\b(?:only )?in (?:valid )?json\b|\bjson only\b|\bonly (?:return|output|respond with) json\b"),
    ("banned_word", r"\b(?:don't|do not|never|stop) (?:use|say|using|saying) the (?:word|term|phrase) [\"'“‘]?([\w-]+(?:'[a-z]+)?(?: [\w-]+)?)[\"'”’]?|"
                    r"\bnever (?:mention|bring up) ([\w-]+)"),
    ("no_emoji", r"\bno emojis?\b|\b(?:don't|do not|stop) (?:use|using|send|sending) emojis?\b|\bwithout emojis?\b"),
    ("lowercase", r"\b(?:all |only |in )?lower ?case\b"),
]
REVOKE = {
    "max_words": r"\byou can (?:go|be|write) longer\b|\b(?:ignore|forget|drop) the (?:word |length )?limit\b|"
                 r"\bno (?:length |word )?limit\b|\blonger answers are (?:fine|ok|okay)\b",
    "language": r"\b(?:switch|go) back to english\b|\byou can (?:reply|answer|write) in english\b|\benglish is (?:fine|ok)\b",
    "no_bullets": r"\bbullets?(?: points)? (?:are|is) (?:fine|ok|okay)(?: again| now)?\b|\byou can use bullets\b",
    "bullets": r"\bno need for bullets\b|\bdrop the bullets\b",
    "json_only": r"\byou can (?:use|reply in|answer in) (?:plain )?text\b|\bno (?:more )?json\b",
    "no_emoji": r"\bemojis? (?:are|is) (?:fine|ok|okay)\b",
    "lowercase": r"\bnormal (?:capitali[sz]ation|case) is (?:fine|ok|okay)\b",
}
REVOKE["max_sentences"] = REVOKE["max_words"]
# A user message right before a reply that asks for something else this time skips the check for that reply.
OVERRIDE = {
    "max_words": r"\b(?:in detail|detailed|elaborate|explain (?:fully|thoroughly)|longer (?:answer|version)|step by step)\b",
    "language": rf"\b(?:in|into|to) {LANG}\b|\btranslat(?:e|ion)\b",
    "json_only": r"\b(?:explain|in (?:plain )?(?:words|text|english)|table|summar(?:y|ize))\b",
    "bullets": r"\b(?:paragraph|prose|essay|e-?mail|letter|story|poem)\b",
    "lowercase": r"\b(?:code|sql|acronyms?|title case|capitali[sz]e)\b",
}
OVERRIDE["max_sentences"] = OVERRIDE["max_words"]
OVERRIDE["no_bullets"] = r"\b(?:as a list|in a list|bullet(?:s| points)?|checklist)\b"
EMOJI = re.compile("[\U0001F000-\U0001FAFF]")  # pictographs only, so ✓ ★ → are not emojis
BULLET_LINE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+\S", re.M)
CODE = re.compile(r"```.*?(?:```|$)|`[^`\n]*`", re.S)


@dataclass
class Constraint:
    kind: str
    param: str
    source_turn: int
    quote: str

    def describe(self) -> str:
        return {
            "max_words": f"at most {self.param} words", "max_sentences": f"at most {self.param} sentences",
            "language": f"reply in {LANGUAGE_NAMES.get(self.param, self.param)}", "bullets": "bullet points",
            "no_bullets": "no bullet points", "json_only": "JSON only", "banned_word": f"never say '{self.param}'",
            "no_emoji": "no emojis", "lowercase": "all lowercase",
        }[self.kind]


def _sentence_constraints(part: str) -> list[tuple[str, str, str]]:
    found, spans = [], []
    for kind, pattern in EXTRACT:
        m = re.search(pattern, part, re.I)
        if not m:
            continue
        if kind == "bullets" and re.search(EXTRACT[3][1], part, re.I):
            continue  # "don't use bullet points" is no_bullets, not bullets
        raw = next((g for g in m.groups() if g), "") if m.groups() else ""
        if kind in ("max_words", "max_sentences"):
            param = str(NUMBER_WORDS.get(raw.lower(), raw))
        elif kind == "language":
            param = LANGUAGES[raw.lower()]
        elif kind == "banned_word":
            param = raw.lower()
        else:
            param = ""
        found.append((kind, param, m.group(0)))
        spans.append(m.span())
    if not found:
        return []
    persistent = re.search(PERSIST, part, re.I) is not None
    if part.rstrip().endswith("?") and not persistent:
        return []  # "Can you reply in one sentence?" asks about this reply
    if re.search(TASK_OBJECT, part, re.I):
        return []  # "... in my wedding invite", "... for the slides", "... to this email"
    rest = part
    for start, end in sorted(spans, reverse=True):
        rest = rest[:start] + " " + rest[end:]
    leftover = set(re.findall(r"[a-z']+", rest.lower())) - BARE
    return found if persistent or not leftover else []


def instruction_ops(text: str) -> list[tuple]:
    """In message order: ("revoke", kind) and ("add", kind, param, quote), sentence by sentence."""
    ops: list[tuple] = []
    for part in re.split(r"(?<=[.!?])\s+", text):
        ops += [("revoke", kind) for kind in sorted(revoked_kinds(part))]
        ops += [("add", *c) for c in _sentence_constraints(part)]
    return ops


def extract_constraints(text: str) -> list[tuple[str, str, str]]:
    """(kind, param, verbatim quote) for each standing reply instruction in a user message."""
    return [op[1:] for op in instruction_ops(text) if op[0] == "add"]


def revoked_kinds(text: str) -> set[str]:
    return {kind for kind, pattern in REVOKE.items() if re.search(pattern, text, re.I)}


def detect_language(text: str) -> Optional[str]:
    """Stopword vote over six languages; None when the text is too short or the vote is unclear."""
    words = re.findall(r"[a-zà-ÿ]+", text.lower())
    if len(words) < 6:
        return None
    scores = {lang: sum(w in sw for w in words) for lang, sw in STOPWORDS.items()}
    best = max(scores, key=scores.get)
    ranked = sorted(scores.values(), reverse=True)
    if ranked[0] < 2 or ranked[0] == ranked[1]:
        return None
    return best


def check(c: Constraint, reply: str) -> Optional[tuple[bool, str, str]]:
    """(kept, what was observed, offending verbatim quote), or None when the reply can't be checked."""
    text = reply.strip()
    if c.kind == "max_words":
        n = len(re.findall(r"[\wÀ-ÿ]+(?:['’.,-][\wÀ-ÿ]+)*", text))  # "3.5" and "well-known" are one word; "-" is none
        return n <= int(c.param), f"{n} words", text
    if c.kind == "max_sentences":
        plain = re.sub(r"\b(?:e\.g|i\.e|etc|vs|dr|mr|mrs|ms|st|no)\.|\d\.\d", "x", text, flags=re.I)
        n = len([s for s in re.split(r"[.!?]+", plain) if s.strip()])
        return n <= int(c.param), f"{n} sentences", text
    if c.kind == "language":
        lang = detect_language(text)
        if lang is None:
            return None
        return lang == c.param, LANGUAGE_NAMES.get(lang, lang), sentence(text)
    if c.kind in ("bullets", "no_bullets"):
        m = BULLET_LINE.search(CODE.sub(lambda x: " " * len(x.group(0)), text))  # lines inside code don't count
        if m is not None:
            m = BULLET_LINE.search(text, m.start())
        if c.kind == "bullets":
            return m is not None, "bullet points" if m else "no bullet points", text
        return m is None, "bullet points" if m else "no bullet points", m.group(0).strip() if m else text
    if c.kind == "json_only":
        body = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
        try:
            json.loads(body)
            return True, "JSON", text
        except ValueError:
            return False, "not JSON", text
    if c.kind == "banned_word":
        m = re.search(rf"(?<!\w){re.escape(c.param)}(?!\w)", text, re.I)
        return m is None, f"said '{m.group(0)}'" if m else "", sentence(text, hint=m.group(0)) if m else text
    if c.kind == "no_emoji":
        m = EMOJI.search(text)
        return m is None, f"emoji {m.group(0)}" if m else "", sentence(text, hint=m.group(0)) if m else text
    if c.kind == "lowercase":
        # Code and acronyms (API, NULL) don't break a lowercase style; other capitals do.
        masked = re.sub(r"\b[A-Z]{2,}\b", lambda x: x.group(0).lower(), CODE.sub(lambda x: x.group(0).lower(), text))
        m = re.search(r"[A-Z]", masked)
        return m is None, "uppercase letters" if m else "", sentence(text, hint=_word_at(text, m.start())) if m else text
    return None


def _word_at(text: str, i: int) -> str:
    m = re.match(r"[\w'-]+", text[i:])
    return m.group(0) if m else text[i]


def detect_constraints(events: list[Event]) -> tuple[list[Finding], int]:
    """CONSTRAINT_DROP findings, and the number of (constraint, reply) pairs that were checked."""
    from .detect import DETECTOR_VERSION

    active: dict[tuple, dict[tuple, Constraint]] = {}  # (user, session) -> {(kind, param or ""): Constraint}
    last_user: dict[tuple, Event] = {}
    findings: list[Finding] = []
    pairs = 0
    for e in sorted(events, key=lambda x: (x.ts, x.index)):
        scope = (e.user_id, e.session_id)
        rules = active.setdefault(scope, {})
        if e.role == "user":
            last_user[scope] = e
            for op in instruction_ops(e.content):  # in order, so "Under 20 words. Actually, go longer." ends revoked
                if op[0] == "revoke":
                    for ident in [i for i in rules if i[0] == op[1]]:
                        del rules[ident]
                    continue
                _, kind, param, quote = op
                slot = (kind, param) if kind == "banned_word" else (kind, "")
                if kind == "bullets":
                    rules.pop(("no_bullets", ""), None)
                if kind == "no_bullets":
                    rules.pop(("bullets", ""), None)
                rules[slot] = Constraint(kind, param, e.index, quote)  # a newer one of the same kind replaces it
            continue
        if e.role != "assistant":
            continue
        prev = last_user.get(scope)
        for c in list(rules.values()):
            override = OVERRIDE.get(c.kind)
            if prev is not None and prev.index != c.source_turn and override and re.search(override, prev.content, re.I):
                continue  # the user just asked for something else this time
            verdict = check(c, e.content)
            if verdict is None:
                continue
            pairs += 1
            kept, observed, quote = verdict
            if kept:
                continue
            findings.append(Finding(
                "constraint_drop", e.user_id, e.session_id, e.ts, e.content, attribute=f"constraint.{c.kind}",
                expected=c.describe(), got=observed, evidence=f'Instruction at turn {c.source_turn}: "{c.quote}"',
                failing_turn=e.index, evidence_turns=[c.source_turn], failing_quote=quote, evidence_quote=c.quote,
                detector=f"rules.constraint_{c.kind}", detector_version=DETECTOR_VERSION))
    return findings, pairs
