# Changelog

## Unreleased
- Fix `recall_continuity`: its denominator counted only the re-asks, so the score was always 0.0. It now counts assistant turns where the user had already given a re-askable fact, and failures are counted per turn.
- Add normalized memory metrics (`memdiag/metrics.py`, `docs/metrics.md`) with explicit denominators.
- Add `--fail-under METRIC=MIN` CI gate (exit 1 on a missed threshold, 2 on bad usage).
- Report metrics in text, HTML and JSON output.
- Add CI workflow, `CLAUDE.md`, dev extras and ruff config.
- Add tag-triggered release workflow, `scripts/release_check.py` and `docs/RELEASING.md`; version is now single-sourced from `memdiag/__init__.py`.
- Add a manual dry-run trigger for the release workflow (no release or publish).
