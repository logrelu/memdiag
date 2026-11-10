# memdiag

Offline eval for agent memory: reads conversation logs, reconstructs what each user said,
and scores the agent on memory behavior. Goal: be to memory what RAGAS is to RAG.

## Commands
- `pip install -e ".[dev]"` (Python >= 3.10; the core has zero runtime dependencies, keep it that way)
- `pytest -q` and `ruff check .` must both pass before any commit
- `memdiag demo` is the end-to-end smoke test

## Layout
- `memdiag/extract.py` rule-based fact extraction (`RuleExtractor`; the seam for an LLM extractor)
- `memdiag/timeline.py` per-user fact timeline built from user messages
- `memdiag/detect.py` per-turn failure detectors -> `Finding`s plus opportunity counts
- `memdiag/metrics.py` normalized 0-1 scores computed from findings and opportunity counts
- `memdiag/strategies.py` memory-strategy replay (`MemoryBackend` is the adapter interface)
- `memdiag/report.py` text, HTML and JSON output; `cli.py`, `mcp_server.py` entry points
- `docs/RELEASING.md` release steps; `scripts/release_check.py` guards the tag, version and changelog
- `docs/metrics.md` the definition of every metric; keep it in sync with `metrics.py`

## Rules
- Every metric needs an explicit denominator ("opportunities") documented in `docs/metrics.md`.
  Never report a score without saying what it was out of.
- A metric with zero opportunities is `None` (not applicable), never 1.0.
- Known extractor misses are recorded as `xfail` in `tests/test_known_limits.py`. Do not delete
  them to make the suite green; fix the extractor or leave them.
- Demo data is synthetic. Do not present demo numbers as benchmark results.
- Work on a branch; do not merge to main without the owner's approval.
