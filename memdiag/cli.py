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
    d.add_argument("traces", help="JSONL of messages: user_id, session_id, ts, role, content[, retrieved, context_tokens]")
    d.add_argument("--docs", help="JSONL of knowledge-base docs: id, text")

    m = sub.add_parser("demo", help="Run on built-in synthetic fintech traces")
    m.add_argument("--write", metavar="DIR", help="Also write the demo traces and docs as JSONL to DIR")

    for sp in (d, m):
        sp.add_argument("--html", help="Write an HTML report")
        sp.add_argument("--json", help="Write a JSON report")
        sp.add_argument("--no-color", action="store_true")
        sp.add_argument("--fail-under", action="append", default=[], metavar="METRIC=MIN",
                        help="Exit 1 if a metric score is below MIN, e.g. deletion_compliance=0.95 (repeatable)")

    args = p.parse_args(argv)
    if args.cmd == "diagnose":
        res = run_files(args.traces, args.docs)
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
