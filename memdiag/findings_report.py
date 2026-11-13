"""The findings report: one card per memory failure, with the failing turn next to the evidence turn.

    html = findings_html(run(events), events)

All log text is HTML-escaped before quotes are highlighted, so a log containing markup cannot inject it.
The page has no scripts.
"""
from __future__ import annotations

import html
from datetime import datetime

from .report import CSS, LABEL
from .schema import Event

EXTRA_CSS = """
.cards{display:grid;gap:14px}.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px 16px}
.card header{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:10px}
.turns{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:10px}
.turn{border:1px solid var(--line);border-radius:6px;padding:10px 12px;font-size:14px;overflow-wrap:anywhere}
.turn .who{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;margin-bottom:4px}
.turn.fail{border-color:color-mix(in srgb,var(--mem) 60%,var(--line))}
mark{background:color-mix(in srgb,var(--ret) 30%,transparent);color:inherit;padding:0 2px;border-radius:3px}
.turn.fail mark{background:color-mix(in srgb,var(--mem) 28%,transparent)}
.meta{margin-top:8px;font-size:13px;color:var(--muted)}.na{opacity:.6}
ul.cant{padding-left:20px}ul.cant li{margin:4px 0}
"""

NA_REASONS = {
    "memory_faithfulness": "no reply asserted a user fact the rules can read",
    "groundedness": "no reply asserted a user fact the rules can read",
    "fact_currency": "no reply mentioned a fact the user had updated",
    "deletion_compliance": "no user asked to forget anything",
    "user_isolation": "no two users stated the same kind of fact",
    "recall_continuity": "no assistant turn came after a fact it could have re-asked",
    "constraint_retention": "no reply came after a checkable instruction (word limit, language, format, banned word)",
}
RULE_ATTRIBUTES = "city, employer, income, credit score and loans"


def _e(s) -> str:
    return html.escape(str(s))


def _mark(text: str, quote: str) -> str:
    """Highlight the first occurrence of `quote` (a verbatim substring) in `text`, escaping each piece.

    The match is found in the raw text, so a quote can never land inside an HTML entity like `&amp;`.
    """
    i = text.find(quote) if quote else -1
    if i < 0:
        return _e(text)
    return f"{_e(text[:i])}<mark>{_e(quote)}</mark>{_e(text[i + len(quote):])}"


def _turn(e: Event, quote: str, kind: str) -> str:
    who = "user" if e.role == "user" else "agent"
    return (f'<div class="turn {kind}"><div class="who">{who} · turn {e.index} · {_e(e.ts.date())}</div>'
            f"{_mark(e.content, quote)}</div>")


def _card(f: dict, by_index: dict[int, Event]) -> str:
    pills = [f'<span class="pill {"mem" if f["class"] == "memory" else "ret"}">{_e(f["type"])}</span>']
    if f.get("location"):
        pills.append(f'<span class="pill">{_e(f["location"])}</span>')
    pills.append(f'<span class="muted">confidence {f["confidence"]:.2f} · {_e(f["user_id"])}'
                 f'{" · " + _e(f["attribute"]) if f["attribute"] else ""}</span>')
    evidence = []
    for n, i in enumerate(f["evidence_turns"]):
        if i in by_index:
            evidence.append(_turn(by_index[i], f["evidence_quote"] if n == 0 else "", "ev"))
    if not evidence and f["evidence_quote"]:
        evidence.append(f'<div class="turn ev"><div class="who">evidence</div>{_mark(f["evidence_quote"], f["evidence_quote"])}</div>')
    failing = by_index.get(f["failing_turn"])
    fail_html = _turn(failing, f["failing_quote"], "fail") if failing else ""
    meta = []
    if f["got"] == "<asked again>":
        meta.append(f'the user had said <b class="ok">{_e(f["expected"])}</b>; the agent asked again')
    elif f["expected"] or f["got"]:
        meta.append(f'expected <b class="ok">{_e(f["expected"])}</b>, the agent used <b class="mem">{_e(f["got"])}</b>')
    meta.append(f'{_e(f["detector"])} v{_e(f["detector_version"])}')
    return (f'<article class="card"><header>{"".join(pills)}</header><div class="turns">{"".join(evidence)}{fail_html}</div>'
            f'<div class="meta">{" · ".join(meta)}</div></article>')


def cant_see(res: dict, events: list[Event]) -> list[str]:
    """What this run could not observe, so a reader doesn't mistake silence for good memory (D7)."""
    out = ["A memory failure that leaves no trace in the reply (the agent quietly ignored a fact) is invisible "
           "here. No findings is not proof of good memory."]
    if not any(e.memory for e in events if e.role == "assistant"):
        out.append("No memory context was logged, so failures can't be split into <b>retrieve</b> (memory never "
                   "supplied the fact) and <b>use</b> (the model ignored it). Add a <code>memory</code> list to "
                   "assistant events to get this.")
    if res.get("mode") == "rules":
        out.append(f"Rules mode reads only {RULE_ATTRIBUTES}. Run with <code>--model</code> to read any fact the "
                   "user states.")
    else:
        out.append(f"Judge and extractor: <b>{_e(res.get('judge_model'))}</b>. Rule hits stand on their own; the "
                   "judge adds and confirms findings. Scores from different judges aren't comparable.")
    for name, m in res["metrics"].items():
        if m["score"] is None:
            out.append(f"<b>{_e(name)}</b> is n/a: {NA_REASONS.get(name, 'it had no opportunities')}.")
    reasons: dict[str, int] = {}
    for d in res.get("ledger_dropped", []):
        reasons[d["reason"]] = reasons.get(d["reason"], 0) + 1
    if reasons:
        total = sum(reasons.values())
        detail = "; ".join(f"{n} {_e(r)}" for r, n in sorted(reasons.items(), key=lambda kv: -kv[1]))
        out.append(f"{total} extracted fact{'s were' if total != 1 else ' was'} dropped ({detail}); see "
                   "<code>memdiag ledger</code>.")
    return out


def findings_html(res: dict, events: list[Event], title: str = "memdiag report") -> str:
    by_index = {e.index: e for e in events}
    users = sorted({e.user_id for e in events})
    st = res["stats"]
    mode = "rules" if res.get("mode") == "rules" else f"local LLM ({_e(res.get('judge_model'))})"
    cards = [f for f in res["findings"] if f["class"] in ("memory", "retrieval")]

    tiles = []
    for name, m in res["metrics"].items():
        if m["score"] is None:
            tiles.append(f'<div class="tile na"><span class="muted">{_e(name)}</span><b>n/a</b>'
                         f'<span class="muted">0 opportunities</span></div>')
        else:
            col = "ok" if m["score"] >= 0.9 else ("ret" if m["score"] >= 0.7 else "mem")
            tiles.append(f'<div class="tile"><span class="muted">{_e(name)}</span><b class="{col}">{m["score"]:.2f}</b>'
                         f'<span class="muted">{m["failures"]} failed of {m["opportunities"]}</span></div>')

    by_type: dict[str, int] = {}
    by_loc = {"retrieve": 0, "use": 0, None: 0}
    for f in cards:
        by_type[f["type"]] = by_type.get(f["type"], 0) + 1
        if f["class"] == "memory":
            by_loc[f.get("location")] = by_loc.get(f.get("location"), 0) + 1
    type_rows = "".join(f"<tr><td>{_e(t)}</td><td class='num'>{n}</td></tr>" for t, n in sorted(by_type.items(), key=lambda kv: -kv[1]))
    loc_line = (f"Memory failures by location: <b>{by_loc['retrieve']}</b> retrieve · <b>{by_loc['use']}</b> use · "
                f"{by_loc[None]} not logged")

    groups = []
    for user in users:
        mine = [f for f in cards if f["user_id"] == user]
        if mine:
            groups.append(f'<h3>{_e(user)} <span class="muted">· {len(mine)} finding{"s" if len(mine) != 1 else ""}</span></h3>'
                          f'<div class="cards">{"".join(_card(f, by_index) for f in mine)}</div>')

    signals = [f for f in res["findings"] if f["class"] in ("signal", "unknown")]
    signal_rows = "".join(
        f"<tr><td>{_e(LABEL[f['category']])}</td><td class='mono'>{_e(f['user_id'])}</td><td>turn {f['failing_turn']}</td>"
        f"<td>{_e(f['evidence_quote'] or f['evidence'])}</td></tr>" for f in signals)

    ledger_rows = []
    chains: dict[tuple, list[dict]] = {}
    for item in res.get("ledger", []):
        chains.setdefault((item["user_id"], item["key"]), []).append(item)
    for (user, key), items in sorted(chains.items()):
        last = items[-1]
        chain = " → ".join(_e(i["value"]) for i in items)
        state = ' <span class="pill muted">deleted</span>' if last["revoked_at_turn"] is not None else ""
        ledger_rows.append(f"<tr><td class='mono'>{_e(user)}</td><td class='mono'>{_e(key)}</td><td>{chain}{state}</td>"
                           f"<td class='ev'>turn {last['source_turn']}: “{_e(last['quote'])}”</td></tr>")

    cant = "".join(f"<li>{line}</li>" for line in cant_see(res, events))
    findings_block = "".join(groups) or '<p class="muted">No memory or retrieval failures found. Read the next section before trusting that.</p>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)}</title><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono&family=IBM+Plex+Sans:wght@400;600&display=swap"><style>{CSS}{EXTRA_CSS}</style></head>
<body><main>
<h1>Memory report</h1>
<p class="muted">{len(users)} user{"s" if len(users) != 1 else ""} · {st['assistant_turns']} agent turns scanned · {len(cards)} findings · {res.get('repair_count', 0)} user repairs · mode: {mode} · {datetime.now().date()}</p>
<h2>Scores</h2><p class="muted">Each score is 1 − failures ÷ opportunities. n/a means the agent never had the chance to fail.</p>
<div class="tiles">{''.join(tiles)}</div>
<h2>Where memory fails</h2><p>{loc_line}</p>
<div class="box"><table><thead><tr><th>Finding type</th><th>Count</th></tr></thead><tbody>{type_rows or '<tr><td colspan=2 class="muted">none</td></tr>'}</tbody></table></div>
<h2>Findings</h2><p class="muted">Each card shows the earlier turn the agent should have remembered, next to the turn where it failed.</p>
{findings_block}
<h2>What this report can't see</h2><ul class="cant">{cant}</ul>
<h2>Signals</h2><p class="muted">Not scored on their own: user repairs ("I already told you") and pushback no rule explains.</p>
<div class="box"><table><thead><tr><th>Signal</th><th>User</th><th>Turn</th><th>What the user said</th></tr></thead><tbody>{signal_rows or '<tr><td colspan=4 class="muted">none</td></tr>'}</tbody></table></div>
<h2>What memdiag thinks each user said</h2>
<div class="box"><table><thead><tr><th>User</th><th>Fact</th><th>Values over time</th><th>Latest quote</th></tr></thead><tbody>{''.join(ledger_rows) or '<tr><td colspan=4 class="muted">no facts extracted</td></tr>'}</tbody></table></div>
<p class="muted" style="margin-top:24px">Generated by memdiag. Every finding quotes the log verbatim; check the quotes, not just the scores.</p>
</main></body></html>"""
