"""Terminal and HTML reports."""
from __future__ import annotations

import html
import json

from .schema import CATEGORIES

LABEL = {k: k.replace("_", " ").capitalize() for k in CATEGORIES}
LABEL.update({"cross_user_leak": "Cross-user leak", "hallucinated_memory": "Invented memory"})

# ---------------------------------------------------------------- terminal --
B, D, R, G, Y, C, X = "\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[33m", "\033[36m", "\033[0m"


def text_report(res: dict, color: bool = True) -> str:
    b, d, r, g, y, c, x = (B, D, R, G, Y, C, X) if color else ("",) * 7
    s, st = res["summary"], res["stats"]
    out = [f"\n{b}memdiag{x} {d}memory diagnostics for AI agents{x}\n"]
    out.append(f"Scanned {st['assistant_turns']} agent answers. {b}{st['failed_turns']}{x} had failures "
               f"({st['user_flagged_turns']} flagged by the user).\n")
    total = s["findings"] or 1
    out.append(f"  {b}Memory failures{x}     {r}{s['memory_failures']:>3}{x}  {'█' * s['memory_failures']}")
    out.append(f"  {b}Retrieval failures{x}  {y}{s['retrieval_failures']:>3}{x}  {'█' * s['retrieval_failures']}")
    out.append(f"  {d}{round(100 * s['memory_failures'] / total)}% of failures are memory problems; "
               f"more RAG tuning won't fix those.{x}\n")

    out.append(f"{b}What went wrong{x}")
    for f in res["findings"]:
        if f["category"] == "context_overload":
            continue
        col = r if f["class"] == "memory" else y
        tag = f" {d}[{', '.join(f['tags'])}]{x}" if f["tags"] else ""
        flag = f" {d}(user flagged){x}" if f["user_flagged"] else ""
        out.append(f"  {col}●{x} {LABEL[f['category']]:<20} {c}{f['user_id']}{x} · {f['attribute']}: "
                   f"expected {g}{f['expected']}{x}, got {r}{f['got']}{x}{flag}{tag}")
    out.append("")

    out.append(f"{b}Which memory approach fits?{x} {d}(replayed {res['probes']} moments where the agent needed a user fact){x}")
    best = s["best_strategy"]
    for row in res["strategies"]:
        pct = round(100 * row["accuracy"])
        bar = "█" * round(pct / 10) + "░" * (10 - round(pct / 10))
        mark = f" {g}← best fit{x}" if best and row["strategy"] == best["strategy"] else ""
        issues = ", ".join(f"{n} {k}" for k, n in [("stale", row["stale"]), ("deleted", row["deleted_exposed"]),
                                                    ("cross-user", row["cross_user"]), ("missing", row["missing"])] if n)
        out.append(f"  {row['strategy']:<28} {bar} {pct:>3}%  {d}{issues}{x}{mark}")
    base = s["full_history_baseline"]
    if best and base:
        out.append(f"\n{b}Bottom line:{x} '{best['strategy']}' answers {round(100 * best['accuracy'])}% of memory "
                   f"moments correctly vs {round(100 * base['accuracy'])}% for stuffing full history into context.")
    out.append(f"{d}Rule-based v0 extractor: covers location, employer, income, loans, credit score.{x}\n")
    return "\n".join(out)


# -------------------------------------------------------------------- html --
CSS = """
:root{--bg:#f7f8f6;--fg:#1d2321;--muted:#5d6763;--panel:#fff;--line:#dfe3e0;--mem:#b4442f;--ret:#a7741a;--ok:#2f7a54;--accent:#2b5d6e}
@media (prefers-color-scheme:dark){:root{--bg:#141817;--fg:#e8ecea;--muted:#9aa5a0;--panel:#1c2120;--line:#2d3432;--mem:#e07a63;--ret:#d9a94f;--ok:#6cc095;--accent:#7fb4c6}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 "IBM Plex Sans",system-ui,sans-serif}
main{max-width:1080px;margin:0 auto;padding:32px max(16px,env(safe-area-inset-left)) 64px}
h1{font:600 28px/1.2 "IBM Plex Sans",system-ui;margin:0 0 4px}h2{font-size:18px;margin:36px 0 12px}
.muted{color:var(--muted)}.mono{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:13px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr));gap:12px;margin-top:20px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px 16px}
.tile b{display:block;font-size:30px;font-weight:600;font-variant-numeric:tabular-nums}
.mem{color:var(--mem)}.ret{color:var(--ret)}.ok{color:var(--ok)}
.split{display:flex;height:14px;border-radius:7px;overflow:hidden;margin:16px 0 6px;background:var(--line)}
.split span{display:block}.box{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-weight:600;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
td.num{text-align:right;font-variant-numeric:tabular-nums}.pill{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;border:1px solid currentColor;white-space:nowrap}
.bar{height:8px;border-radius:4px;background:var(--line);min-width:120px}.bar i{display:block;height:100%;border-radius:4px;background:var(--accent)}
.best td{background:color-mix(in srgb,var(--ok) 10%,transparent)}.ev{color:var(--muted);font-size:13px}
"""


def _e(s) -> str:
    return html.escape(str(s))


def html_report(res: dict, title: str = "memdiag report") -> str:
    s, st = res["summary"], res["stats"]
    total = max(s["findings"], 1)
    mem_w, ret_w = 100 * s["memory_failures"] / total, 100 * s["retrieval_failures"] / total
    best = s["best_strategy"]
    rows = []
    for f in res["findings"]:
        cls = {"memory": "mem", "retrieval": "ret"}.get(f["class"], "muted")
        tags = "".join(f' <span class="pill muted">{_e(t)}</span>' for t in f["tags"])
        flag = ' <span class="pill muted">user flagged</span>' if f["user_flagged"] else ""
        rows.append(
            f"<tr><td><span class='pill {cls}'>{_e(LABEL[f['category']])}</span>{flag}{tags}</td>"
            f"<td class='mono'>{_e(f['user_id'])}</td><td>{_e(f['attribute'])}</td>"
            f"<td class='ok mono'>{_e(f['expected'])}</td><td class='{cls} mono'>{_e(f['got'])}</td>"
            f"<td>{_e(f['turn'])}<div class='ev'>{_e(f['evidence'])}</div></td></tr>")
    strat = []
    for r in res["strategies"]:
        pct = round(100 * r["accuracy"])
        cls = " class='best'" if best and r["strategy"] == best["strategy"] else ""
        strat.append(
            f"<tr{cls}><td><b>{_e(r['strategy'])}</b><div class='ev'>{_e(r['description'])}</div></td>"
            f"<td><div class='bar'><i style='width:{pct}%'></i></div></td><td class='num'>{pct}%</td>"
            f"<td class='num'>{r['stale']}</td><td class='num'>{r['deleted_exposed']}</td>"
            f"<td class='num'>{r['cross_user']}</td><td class='num'>{r['missing']}</td><td class='num'>{r['avg_tokens']}</td></tr>")
    tl = "".join(
        f"<tr><td class='mono'>{_e(t['user_id'])}</td><td>{_e(t['attribute'])}</td><td class='mono'>{_e(t['value'])}</td>"
        f"<td class='mono'>{_e(t['ts'][:10])}</td><td class='ev'>{_e(t['source'])}</td></tr>" for t in res["timeline"])
    base = s["full_history_baseline"]
    bottom = ""
    if best and base:
        bottom = (f"<p><b>Bottom line:</b> <b>{_e(best['strategy'])}</b> answered {round(100 * best['accuracy'])}% of memory moments "
                  f"correctly, versus {round(100 * base['accuracy'])}% for putting full history in context.</p>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)}</title><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono&family=IBM+Plex+Sans:wght@400;600&display=swap"><style>{CSS}</style></head>
<body><main>
<h1>Memory diagnostics</h1><p class="muted">{st['assistant_turns']} agent answers scanned · {res['probes']} moments that needed a user fact · rule-based v0</p>
<div class="tiles">
<div class="tile"><span class="muted">Answers with failures</span><b>{st['failed_turns']}</b></div>
<div class="tile"><span class="muted">Memory failures</span><b class="mem">{s['memory_failures']}</b></div>
<div class="tile"><span class="muted">Retrieval failures</span><b class="ret">{s['retrieval_failures']}</b></div>
<div class="tile"><span class="muted">Flagged by users</span><b>{st['user_flagged_turns']}</b></div></div>
<div class="split"><span style="width:{mem_w:.1f}%;background:var(--mem)"></span><span style="width:{ret_w:.1f}%;background:var(--ret)"></span></div>
<p class="muted">{round(mem_w)}% of failures are memory problems. Tuning retrieval won't fix those.</p>
<h2>Which memory approach fits?</h2>
<p class="muted">Each user's history replayed through candidate strategies, scored on whether they would have recalled the user's current facts.</p>
<div class="box"><table><thead><tr><th>Strategy</th><th></th><th>Correct</th><th>Stale</th><th>Deleted shown</th><th>Cross-user</th><th>Missing</th><th>~Tokens</th></tr></thead><tbody>{''.join(strat)}</tbody></table></div>
{bottom}
<h2>What went wrong</h2>
<div class="box"><table><thead><tr><th>Failure</th><th>User</th><th>Fact</th><th>Expected</th><th>Agent used</th><th>Answer and evidence</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<h2>Reconstructed user timeline</h2>
<div class="box"><table><thead><tr><th>User</th><th>Fact</th><th>Value</th><th>Stated</th><th>Source message</th></tr></thead><tbody>{tl}</tbody></table></div>
<p class="muted" style="margin-top:24px">Generated by memdiag v0. Extraction is rule-based and covers location, employer, income, loans and credit score.</p>
</main></body></html>"""


def json_report(res: dict) -> str:
    return json.dumps(res, indent=2, default=str)
