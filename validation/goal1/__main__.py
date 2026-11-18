"""python -m validation.goal1 [--mode rules|llm] [--model qwen2.5:7b] [--limit N] [--reruns 3] [--run NAME]"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import memdiag
from memdiag import Event, run

from .mutate import PINNED_SHA256, build_suite, sha256, to_events, write_suite
from .report import write_report
from .score import aggregate, base_id, score_case

ROOT = Path(__file__).resolve().parents[2]


def _clean_filter(stats: dict):
    def is_clean(base) -> bool:
        stats["checked"] += 1
        rows = to_events("base", [base])
        res = run([Event.from_dict(r, i) for i, r in enumerate(rows)])
        clean = not res["findings"]
        stats["rejected"] += not clean
        return clean
    return is_clean


def _first(cases: list[dict], n: int) -> list[dict]:
    """The first n positives per type and split, with their controls (paired and history)."""
    keep = {c["case_id"] for c in cases if not c["control"] and int(c["case_id"].rsplit("-", 1)[1]) < n}
    return [c for c in cases if base_id(c["case_id"]) in keep]


def _cost(cases: list[dict], seconds: float, judge) -> dict:
    """Goal 1 criterion 5: wall time and model calls per 100 sessions. Cached calls cost nothing here but would for
    a new user, so the estimate charges every call at the mean time of the uncached ones."""
    sessions = sum(len({e["session_id"] for e in c["events"]}) for c in cases)
    out = {"sessions": sessions, "wall_seconds": round(seconds, 1),
           "machine": f"{platform.system()} {platform.machine()}, {os.cpu_count()} CPUs"}
    if judge is not None:
        roles = judge.usage.by_role
        calls = sum(u["calls"] for u in roles.values())
        fresh = sum(u["calls"] - u["cached"] for u in roles.values())
        fresh_s = sum(u["seconds"] for u in roles.values())
        out.update({"calls": calls, "uncached_calls": fresh, "by_role": {k: dict(v) for k, v in roles.items()},
                    "calls_per_100_sessions": round(100 * calls / max(1, sessions), 1),
                    "est_seconds_per_100_sessions": round(100 * calls * fresh_s / max(1, fresh) / max(1, sessions))
                    if fresh else None})
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m validation.goal1")
    p.add_argument("--mode", choices=["rules", "llm"], default="rules")
    p.add_argument("--model", default="qwen2.5:7b")
    p.add_argument("--base-url")
    p.add_argument("--limit", type=int, help="score only the first N positives (and their controls) per type and split")
    p.add_argument("--split", choices=["dev", "heldout"], help="score only this split")
    p.add_argument("--reruns", type=int, default=0, help="LLM mode: uncached reruns on held-out cases for the flip rate")
    p.add_argument("--rerun-limit", type=int, help="reruns use only the first N positives per type (and their controls)")
    p.add_argument("--run", help="run name: results go to goal1_<mode>_<run>.json, next to earlier runs")
    p.add_argument("--data", default=str(ROOT / "experiments/data/longmemeval_s_cleaned.json"))
    p.add_argument("--suite", default=str(ROOT / "validation/data/goal1_suite.jsonl"))
    p.add_argument("--rebuild", action="store_true")
    p.add_argument("--report-only", action="store_true", help="regenerate docs/validation.md from saved results")
    args = p.parse_args(argv)
    if args.report_only:
        write_report(ROOT / "validation/results", ROOT / "docs/validation.md")
        return 0

    data = Path(args.data)
    if not data.exists():
        print(f"Missing {data}. Download longmemeval_s_cleaned.json from "
              "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned (MIT).", file=sys.stderr)
        return 2
    digest = sha256(data)
    if digest != PINNED_SHA256:
        print(f"{data} has sha256 {digest}, expected {PINNED_SHA256}; results would not be comparable.", file=sys.stderr)
        return 2
    suite_path, meta_path = Path(args.suite), Path(args.suite).with_suffix(".meta.json")
    if args.rebuild or not suite_path.exists():
        stats = {"checked": 0, "rejected": 0}
        cases = build_suite(data, is_clean=_clean_filter(stats))
        write_suite(cases, suite_path)
        meta_path.write_text(json.dumps({"background": stats}))
    cases = [json.loads(line) for line in suite_path.read_text().splitlines()]
    background = json.loads(meta_path.read_text())["background"]
    if args.limit:
        cases = _first(cases, args.limit)

    if args.split:
        cases = [c for c in cases if c["split"] == args.split]

    judge = None
    if args.mode == "llm":
        from memdiag.judge import DiskCache, OpenAICompatJudge
        judge = OpenAICompatJudge(args.model, base_url=args.base_url, cache=DiskCache(ROOT / ".memdiag_cache"))
    rows, started = [], time.time()
    for i, case in enumerate(cases, 1):
        rows.append(score_case(case, judge))
        if args.mode == "llm" and i % 10 == 0:
            print(f"{i}/{len(cases)} cases", flush=True)

    seconds = time.time() - started
    flip = None
    if args.mode == "llm" and args.reruns:
        from memdiag.judge import OpenAICompatJudge
        sample = [c for c in cases if c["split"] == "heldout"]
        if args.rerun_limit:
            sample = _first(sample, args.rerun_limit)
        first = {r["case_id"]: tuple(r["found_turns"]) for r in rows}  # any change in findings counts as a flip
        verdicts = {c["case_id"]: [first[c["case_id"]]] for c in sample}  # the original run counts too
        for _ in range(args.reruns):
            fresh = OpenAICompatJudge(args.model, base_url=args.base_url)  # no cache: a real rerun
            for c in sample:
                r = score_case(c, fresh)
                verdicts[c["case_id"]].append(tuple(r["found_turns"]))
        flipped = sum(len(set(v)) > 1 for v in verdicts.values())
        flip = {"reruns": args.reruns, "cases": len(sample), "flipped": flipped, "rate": flipped / max(1, len(sample)),
                "verdict": "any change in the turns with a finding of the case's type",
                "flipped_ids": sorted(k for k, v in verdicts.items() if len(set(v)) > 1)}

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    meta = {"mode": args.mode, "judge_model": args.model if judge else None, "date": str(date.today()),
            "memdiag_version": memdiag.__version__, "commit": commit, "data_sha256": digest, "cases": len(cases),
            "limit": args.limit, "split": args.split, "background": background, "run": args.run,
            "cost": _cost(cases, seconds, judge)}
    out_dir = ROOT / "validation/results"
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {"meta": meta, "aggregate": aggregate(rows), "rows": rows, "flip": flip}
    (out_dir / f"goal1_{args.mode}{'_' + args.run if args.run else ''}.json").write_text(json.dumps(result, indent=1))
    write_report(out_dir, ROOT / "docs/validation.md")
    held = result["aggregate"].get("heldout|ALL|all") or next(iter(result["aggregate"].values()))
    print(f"{args.mode}: held-out recall {held['recall']['rate']:.2f}, exact turn {held['exact_turn']['rate']:.2f}, "
          f"false positives {held['false_positive']['rate']:.2f} -> docs/validation.md")
    if judge is not None:
        print(judge.usage.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
