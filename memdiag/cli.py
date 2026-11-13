"""memdiag command line.

    memdiag diagnose traces.jsonl [--docs docs.jsonl] [--html report.html] [--json out.json]
    memdiag demo [--html report.html]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import Event, check_thresholds, run, run_files
from .adapters import FORMATS
from .report import html_report, json_report, text_report


def _emit(res, args):
    print(text_report(res, color=sys.stdout.isatty() and not args.no_color))
    if args.html:
        Path(args.html).write_text(html_report(res))
        print(f"HTML report: {args.html}")
    if args.json:
        Path(args.json).write_text(json_report(res))
        print(f"JSON report: {args.json}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="memdiag", description="Memory diagnostics for AI agents")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("diagnose", help="Diagnose an agent's conversation logs")
    d.add_argument("traces", help="Log file: memdiag events JSONL, OpenAI-style conversations, or LongMemEval items")
    d.add_argument("--format", default="auto", choices=FORMATS, help="Log format (default: detect from the file)")
    d.add_argument("--docs", help="JSONL of knowledge-base docs: id, text")

    lg = sub.add_parser("ledger", help="Show the facts each user stated, with updates and deletions")
    lg.add_argument("traces", help="Log file in any supported format")
    lg.add_argument("--format", default="auto", choices=FORMATS)
    lg.add_argument("--model", help="Also extract with this model via an OpenAI-compatible endpoint "
                                    "(default endpoint: local Ollama). Without it, rules only.")
    lg.add_argument("--base-url", help="Model endpoint, e.g. http://localhost:11434/v1 (or MEMDIAG_BASE_URL)")
    lg.add_argument("--cache", default=".memdiag_cache", help="Judge cache directory (default: .memdiag_cache)")
    lg.add_argument("--out", help="Write ledger items as JSONL")

    m = sub.add_parser("demo", help="Run on built-in synthetic fintech traces")
    m.add_argument("--write", metavar="DIR", help="Also write the demo traces and docs as JSONL to DIR")

    for sp in (d, m):
        sp.add_argument("--html", help="Write an HTML report")
        sp.add_argument("--json", help="Write a JSON report")
        sp.add_argument("--no-color", action="store_true")
        sp.add_argument("--fail-under", action="append", default=[], metavar="METRIC=MIN",
                        help="Exit 1 if a metric score is below MIN, e.g. deletion_compliance=0.95 (repeatable)")

    args = p.parse_args(argv)
    if args.cmd == "ledger":
        return _ledger(args)
    if args.cmd == "diagnose":
        try:
            res = run_files(args.traces, args.docs, args.format)
        except (OSError, ValueError) as exc:
            print(f"memdiag: {exc}", file=sys.stderr)
            return 2
    else:
        from .demo_data import DOCS, TRACES
        if args.write:
            out = Path(args.write)
            out.mkdir(parents=True, exist_ok=True)
            (out / "traces.jsonl").write_text("\n".join(json.dumps(t) for t in TRACES) + "\n")
            (out / "docs.jsonl").write_text("\n".join(json.dumps(x) for x in DOCS) + "\n")
            print(f"Wrote {out}/traces.jsonl and {out}/docs.jsonl")
        res = run([Event.from_dict(t, i) for i, t in enumerate(TRACES)], DOCS)
    _emit(res, args)
    return _gate(res, args.fail_under)


def _ledger(args) -> int:
    from .adapters import load
    from .judge import DiskCache, JudgeUnavailable, OpenAICompatJudge
    from .ledger import build_ledger

    judge = None
    if args.model:
        judge = OpenAICompatJudge(args.model, base_url=args.base_url, cache=DiskCache(args.cache))
    try:
        ledger = build_ledger(load(args.traces, args.format), judge=judge)
    except (OSError, ValueError, JudgeUnavailable) as exc:
        print(f"memdiag: {exc}", file=sys.stderr)
        return 2
    by_id = {i.item_id: i for i in ledger.items}
    for user in sorted({i.user_id for i in ledger.items}):
        print(user)
        for key in ledger.keys_for(user):
            chain = ledger.history(user, key)
            live = ledger.current(user, key)
            shown = " -> ".join(i.value for i in chain)
            state = "" if live else "  (deleted)"
            last = chain[-1]
            print(f"  {key:24s} {shown}{state}   [turn {last.source_turn}, {last.extractor}: \"{last.quote}\"]")
    s = ledger.stats
    superseded = sum(1 for i in ledger.items if i.superseded_by in by_id)
    print(f"\n{s['items']} facts from {s['messages']} user messages ({s['llm_messages']} sent to the model), "
          f"{superseded} updates, {s['dropped']} model facts dropped (quote not in the message or incomplete)")
    if judge is not None:
        print(judge.usage.summary())
    if args.out:
        Path(args.out).write_text("".join(json.dumps(r) + "\n" for r in ledger.to_rows()))
        print(f"Wrote {args.out}")
    return 0


def _gate(res, specs) -> int:
    try:
        thresholds = {k: float(v) for k, v in (spec.split("=", 1) for spec in specs)}
    except ValueError:
        print("error: --fail-under expects METRIC=NUMBER, e.g. user_isolation=0.99", file=sys.stderr)
        return 2
    from .metrics import Metric
    metrics = {k: Metric(**m) for k, m in res["metrics"].items()}
    problems = check_thresholds(metrics, thresholds)
    for msg in problems:
        print(f"FAIL: {msg}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
