"""Build the Goal 1 mutation suite: clean LongMemEval sessions with exactly one injected failure (or a control).

    python -m validation.goal1 --mode rules        # builds the suite if needed, scores it, writes the report

Every positive case has a paired control built from the same base sessions and template slot, differing only
in the injected text, so false positives are measured on the same scaffolding.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path

from . import templates as T

PINNED_SHA256 = "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442"
MAX_TURNS, MAX_CHARS = 8, 600
COUNTS = {"dev": 40, "heldout": 25}  # positive cases per type and split; each has a paired control
TYPES = ("STALE_FACT", "RECALL_MISS", "CONSTRAINT_DROP", "USER_REPAIR")
MAX_WORDS = 25
EMOJI = re.compile("[\U0001F000-\U0001FAFF]")
LIST_MARK = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+", re.M)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def session_split(session_id: str) -> str:
    return T.HELDOUT if int(hashlib.sha1(session_id.encode()).hexdigest(), 16) % 10 < 3 else T.DEV


def _trim(text: str) -> str:
    if len(text) <= MAX_CHARS:
        return text.strip()
    cut = text[:MAX_CHARS]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return (cut[:end + 1] if end > 200 else cut).strip()


def load_bases(path: Path) -> list[tuple[str, list[list[str]]]]:
    """Unique LongMemEval sessions, as (session id, [[role, text], ...]) with user/assistant turns alternating."""
    data = json.loads(Path(path).read_text())
    seen: dict[str, list[list[str]]] = {}
    for item in data:
        for sid, sess in zip(item["haystack_session_ids"], item["haystack_sessions"], strict=True):
            if sid in seen:
                continue
            turns = [[t["role"], _trim(t["content"])] for t in sess[:MAX_TURNS]]
            roles = [r for r, _ in turns]
            if len(turns) == MAX_TURNS and roles == ["user", "assistant"] * (MAX_TURNS // 2):
                seen[sid] = turns
    return sorted(seen.items())


def to_events(case_id: str, sessions: list[tuple[str, list[list[str]]]]) -> list[dict]:
    rows = []
    for day, (sid, turns) in enumerate(sessions):
        for j, (role, text) in enumerate(turns):
            rows.append({"user_id": case_id, "session_id": f"{case_id}:{sid}",
                         "ts": f"2026-01-{day + 1:02d}T10:{j // 60:02d}:{j % 60:02d}", "role": role, "content": text})
    return rows


def _first_assistant(turns: list[list[str]], start: int = 0) -> int:
    return next(i for i in range(start, len(turns)) if turns[i][0] == "assistant")


def _offset(sessions: list[tuple[str, list]], s: int, i: int) -> int:
    return sum(len(t) for _, t in sessions[:s]) + i


# ---------------------------------------------------------------- case builders --
def stale_case(rng, split, bases, attr):
    pool = T.CITIES if attr == "city" else T.EMPLOYERS
    old, new = rng.sample(pool, 2)
    f, u = T.pick(T.FACT[attr], split, rng), T.pick(T.UPDATE[attr], split, rng)
    s, c = T.pick(T.STALE[attr], split, rng), T.pick(T.STALE_CONTROL[attr], split, rng)
    b1, b2, b3 = ([list(t) for t in turns] for _, turns in bases)
    s1 = [["user", f["text"].format(v=old)], ["assistant", T.ACK]] + b1
    s2 = [["user", u["text"].format(v=new, old=old)], ["assistant", T.ACK]] + b2
    target = _first_assistant(b3)
    pos, ctl = [list(t) for t in b3], [list(t) for t in b3]
    pos[target][1] = s["text"].format(v=old) + " " + pos[target][1]
    ctl[target][1] = c["text"].format(old=old, new=new) + " " + ctl[target][1]
    ids = [f["id"], u["id"]]
    sessions = lambda last: [(bases[0][0], s1), (bases[1][0], s2), (bases[2][0], last)]  # noqa: E731
    gold = _offset(sessions(pos), 2, target)
    return (sessions(pos), gold, ids + [s["id"]]), (sessions(ctl), None, ids + [c["id"]])


def reask_case(rng, split, bases, attr):
    name, age = rng.choice(T.CHILD_NAMES), str(rng.randint(4, 12))
    value = age if attr == "child_age" else rng.choice(T.CITIES if attr == "city" else T.EMPLOYERS)
    f, q, c = T.pick(T.FACT[attr], split, rng), T.pick(T.REASK[attr], split, rng), T.pick(T.REASK_CONTROL, split, rng)
    b1, b2 = ([list(t) for t in turns] for _, turns in bases[:2])
    s1 = [["user", f["text"].format(v=value, name=name)], ["assistant", T.ACK]] + b1
    target = _first_assistant(b2)
    pos, ctl = [list(t) for t in b2], [list(t) for t in b2]
    pos[target][1] = q["text"].format(name=name) + " " + pos[target][1]
    ctl[target][1] = c["text"] + " " + ctl[target][1]
    sessions = lambda last: [(bases[0][0], s1), (bases[1][0], last)]  # noqa: E731
    gold = _offset(sessions(pos), 1, target)
    return (sessions(pos), gold, [f["id"], q["id"]]), (sessions(ctl), None, [f["id"], c["id"]])


def _comply(kind: str, text: str, word: str) -> str:
    if kind == "max_words":
        words = text.split()
        return " ".join(words[:MAX_WORDS // 2]).rstrip(".,;:!?") + "."
    if kind == "no_bullets":
        return LIST_MARK.sub("", text)
    if kind == "banned_word":
        return re.sub(rf"(?<!\w){re.escape(word)}\w*", "approach", text, flags=re.I)
    if kind == "no_emoji":
        return EMOJI.sub("", text)
    return text


def _break(kind: str, text: str, word: str) -> str:
    base = _comply(kind, text, word) if kind != "max_words" else text
    if kind == "max_words":
        while len(base.split()) <= MAX_WORDS + 5:
            base += " Here is some more detail so that this answer runs well past the requested word limit."
        return base
    if kind == "no_bullets":
        return base + "\n- the first option\n- the second option"
    if kind == "banned_word":
        return base + f" The {word} angle matters here."
    return base + " 🎉"


def constraint_case(rng, split, bases, kind):
    word = rng.choice(T.BANNED)
    k = T.pick(T.CONSTRAINT[kind], split, rng)
    turns = [["user", k["text"].format(n=MAX_WORDS, w=word)], ["assistant", "Understood."]] + [list(t) for t in bases[0][1]]
    target = max(i for i, (r, _) in enumerate(turns) if r == "assistant")
    for i, (role, text) in enumerate(turns):
        if role == "assistant" and 1 < i < target:
            turns[i][1] = _comply(kind, text, word)
    pos, ctl = [list(t) for t in turns], [list(t) for t in turns]
    pos[target][1] = _break(kind, pos[target][1], word)
    if kind in T.CONSTRAINT_REVOKE and rng.random() < 0.5:  # control: the user lifted it before the long reply
        ctl[target - 1][1] = ctl[target - 1][1] + " " + T.CONSTRAINT_REVOKE[kind]
        ctl[target][1] = _break(kind, ctl[target][1], word)
        cid = "revoked"
    else:  # control: the reply keeps the instruction
        ctl[target][1] = _comply(kind, ctl[target][1], word)
        cid = "complies"
    sid = bases[0][0]
    return ([(sid, pos)], target, [k["id"]]), ([(sid, ctl)], None, [k["id"], cid])


def repair_case(rng, split, bases, _attr):
    p, c = T.pick(T.REPAIR, split, rng), T.pick(T.REPAIR_CONTROL, split, rng)
    turns = [list(t) for t in bases[0][1]]
    target = 3  # the second assistant turn
    pos = turns[:target + 1] + [["user", p["text"]]] + turns[target + 1:]
    ctl = turns[:target + 1] + [["user", c["text"]]] + turns[target + 1:]
    sid = bases[0][0]
    return ([(sid, pos)], target, [p["id"]]), ([(sid, ctl)], None, [c["id"]])


BUILDERS = {
    "STALE_FACT": (stale_case, 3, ["city", "employer"]),
    "RECALL_MISS": (reask_case, 2, ["city", "employer", "child_age"]),
    "CONSTRAINT_DROP": (constraint_case, 1, ["max_words", "no_bullets", "banned_word", "no_emoji"]),
    "USER_REPAIR": (repair_case, 1, ["repair"]),
}


def build_suite(data_path: Path, seed: int = 7, is_clean=None) -> list[dict]:
    """Deterministic suite from the pinned LongMemEval file. `is_clean(turns)` filters base sessions."""
    rng = random.Random(seed)
    bases = load_bases(data_path)
    rng.shuffle(bases)
    pools = {T.DEV: [b for b in bases if session_split(b[0]) == T.DEV],
             T.HELDOUT: [b for b in bases if session_split(b[0]) == T.HELDOUT]}
    cursor = {T.DEV: 0, T.HELDOUT: 0}

    def take(split: str, n: int) -> list:
        out = []
        while len(out) < n:
            b = pools[split][cursor[split]]
            cursor[split] += 1
            if is_clean is None or is_clean(b):
                out.append(b)
        return out

    cases = []
    for typ in TYPES:
        builder, n_bases, attrs = BUILDERS[typ]
        for split, count in COUNTS.items():
            for i in range(count):
                attr = attrs[i % len(attrs)]
                pos, ctl = builder(rng, split, take(split, n_bases), attr)
                for (sessions, gold, tids), control in ((pos, False), (ctl, True)):
                    case_id = f"{typ.lower()}-{split}-{i:03d}{'-ctl' if control else ''}"
                    cases.append({"case_id": case_id, "type": typ, "split": split, "attr": attr, "control": control,
                                  "template_ids": tids, "gold_turn": gold, "events": to_events(case_id, sessions)})
    return cases


def write_suite(cases: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(c) + "\n" for c in cases))
