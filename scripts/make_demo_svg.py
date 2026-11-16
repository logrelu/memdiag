"""Regenerate docs/demo.svg, the README's terminal demo, from real command output.

    python scripts/make_demo_svg.py --cache .memdiag_cache

Each command really runs (with --model qwen2.5:7b, so it needs Ollama or a warm cache), and its output is
written into an animated SVG: the command types out, then the output appears line by line. Stdlib only.
"""
from __future__ import annotations

import argparse
import html
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from memdiag.schema import TYPES  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MODEL = "qwen2.5:7b"
LOG = "examples/walkthrough.jsonl"

W, PAD, LINE, CHAR = 860, 18, 18, 7.8  # px; CHAR is the advance of 13px monospace
TYPE_S, LINE_S, PAUSE_S, HOLD_S = 0.035, 0.07, 1.2, 6.0  # seconds
BG, FG, DIM, PROMPT, HEAD, OK, BAD = "#0d1117", "#e6edf3", "#8b949e", "#7ee787", "#ffa657", "#7ee787", "#ff7b72"


def scenes(cache: str, out_dir: str) -> list[tuple[str, list[str]]]:
    cmds = [
        (f"memdiag ledger {LOG} --model {MODEL}", ["ledger", LOG, "--model", MODEL, "--cache", cache]),
        (f"memdiag run {LOG} --model {MODEL}",
         ["run", LOG, "--model", MODEL, "--cache", cache, "--html", f"{out_dir}/report.html",
          "--findings", f"{out_dir}/findings.jsonl"]),
    ]
    out = []
    for shown, argv in cmds:
        r = subprocess.run([sys.executable, "-m", "memdiag.cli", *argv], cwd=ROOT, capture_output=True, text=True,
                           env={**os.environ, "PYTHONPATH": str(ROOT)})  # this checkout, not another install
        if r.returncode not in (0, 1):
            sys.exit(f"`{shown}` failed:\n{r.stderr}")
        lines = [ln.replace(f"{out_dir}/", "") for ln in r.stdout.rstrip("\n").splitlines()]
        # The per-role call table is noise in a demo; the run's own summary line says it was local.
        lines = [ln for ln in lines if " calls (" not in ln]
        out.append((shown, lines))
    return out


def colour(line: str) -> str:
    if line.split(" · ")[0] in set(TYPES.values()):
        return HEAD
    if line.startswith("  user,"):
        return OK
    if line.startswith("  agent,"):
        return BAD
    if line.startswith(("Scores", "Findings:", "Report:")) or "n/a" in line:
        return DIM
    return FG


def build(scene_list: list[tuple[str, list[str]]]) -> str:
    events, t, y = [], 0.5, PAD + 14  # (start second, svg element) pairs
    rows = []
    for shown, lines in scene_list:
        rows.append(("cmd", shown, y, t))
        t += len(shown) * TYPE_S + 0.5
        y += LINE
        for ln in lines:
            rows.append(("out", ln, y, t))
            t += LINE_S
            y += LINE
        y += LINE
        t += PAUSE_S
    total = t + HOLD_S
    height = y + PAD

    def show_at(start: float) -> str:
        p = 100 * start / total
        return f"0%,{p:.3f}%{{opacity:0}}{min(p + 0.01, 100):.3f}%,100%{{opacity:1}}"

    styles, n = [], 0
    for kind, text, ry, start in rows:
        if kind == "cmd":
            spans = [f'<tspan fill="{PROMPT}">$ </tspan>']
            for i, ch in enumerate(text):
                n += 1
                styles.append(f".a{n}{{animation:k{n} {total:.2f}s step-end infinite}}@keyframes k{n}{{{show_at(start + i * TYPE_S)}}}")
                spans.append(f'<tspan class="a{n}">{html.escape(ch)}</tspan>')
            events.append(f'<text x="{PAD}" y="{ry}" fill="{FG}" xml:space="preserve">{"".join(spans)}</text>')
        else:
            n += 1
            styles.append(f".a{n}{{animation:k{n} {total:.2f}s step-end infinite}}@keyframes k{n}{{{show_at(start)}}}")
            events.append(f'<text class="a{n}" x="{PAD}" y="{ry}" fill="{colour(text)}" xml:space="preserve">'
                          f"{html.escape(text)}</text>")
    width = max(W, int(PAD * 2 + CHAR * max(len(t) + 2 for _, t, _, _ in rows)))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'role="img" aria-label="memdiag finding memory failures in a sample agent log">'
            f"<style>text{{font:13px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}{''.join(styles)}</style>"
            f'<rect width="100%" height="100%" rx="8" fill="{BG}"/>{"".join(events)}</svg>\n')


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cache", default=".memdiag_cache")
    p.add_argument("--out", default=str(ROOT / "docs/demo.svg"))
    args = p.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        svg = build(scenes(str(Path(args.cache).resolve()), tmp))
    Path(args.out).write_text(svg)
    print(f"Wrote {args.out} ({len(svg) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
