# Changelog

## Unreleased
- Add normalized memory metrics (`memdiag/metrics.py`, `docs/metrics.md`) with explicit denominators.
- Add `--fail-under METRIC=MIN` CI gate (exit 1 on a missed threshold, 2 on bad usage).
- Report metrics in text, HTML and JSON output.
- Add CI workflow, `CLAUDE.md`, dev extras and ruff config.
