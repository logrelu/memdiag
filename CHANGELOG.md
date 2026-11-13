# Changelog

## Unreleased
- Findings are localized: each one records `failing_turn`, `evidence_turns`, verbatim `failing_quote` and `evidence_quote`, its `detector` and `detector_version`, a stable `type` (e.g. `STALE_FACT`) and `mode`, and covariates. Existing keys are unchanged.
- New `memdiag.adapters`: read OpenAI-style conversations and LongMemEval items directly; `memdiag diagnose --format` (auto-detected by default).
- Events accept an optional `memory` list for the memory context injected into a call.
- Fix `recall_continuity`: its denominator counted only the re-asks, so the score was always 0.0. It now counts assistant turns where the user had already given a re-askable fact, and failures are counted per turn.
- Add normalized memory metrics (`memdiag/metrics.py`, `docs/metrics.md`) with explicit denominators.
- Add `--fail-under METRIC=MIN` CI gate (exit 1 on a missed threshold, 2 on bad usage).
- Report metrics in text, HTML and JSON output.
- Add CI workflow, `CLAUDE.md`, dev extras and ruff config.
- Add tag-triggered release workflow, `scripts/release_check.py` and `docs/RELEASING.md`; version is now single-sourced from `memdiag/__init__.py`.
- Add a manual dry-run trigger for the release workflow (no release or publish).
