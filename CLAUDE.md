# memdiag

Eval for agent memory: reads the logs an agent already writes and reports each memory failure at the
turn it happened, with the earlier turn it contradicts, quoted, and scores built from those findings.
Goal: be to memory what RAGAS is to RAG, with published validation numbers.

Read `docs/ROADMAP.md` before any task. It holds the goals, design decisions D1-D13, milestones and success criteria.

## Commands
- `pip install -e ".[dev]"` into `.venv` (Python >= 3.10). Verify with an editable install; a non-editable one tests stale code.
- `ruff check .` and `pytest -q` must both pass before any commit.
- `memdiag demo` is the end-to-end smoke test; `memdiag run LOG` is the primary command.
- Local judge: `ollama serve`, model `qwen2.5:7b` (16 GB Mac reference). Experiments live in `experiments/`; their data goes in `experiments/data/` (git-ignored).

## Layout
- `memdiag/extract.py` rule-based extraction (`RuleExtractor`); `timeline.py` per-user fact timeline
- `memdiag/detect.py` detectors -> `Finding`s and opportunity counts; `metrics.py` scores from findings
- `memdiag/strategies.py` memory-strategy replay; `report.py` text/HTML/JSON for `diagnose`; `findings_report.py` the `run` report; `cli.py`, `mcp_server.py`
- `memdiag/adapters.py` log formats -> `Event`s (events, openai, longmemeval)
- `memdiag/detectors.py` ledger detectors (stale mentions, re-ask patterns + judge, user repair, retrieve/use); merged with `detect.py` in `run()`
- `memdiag/ledger.py` the fact ledger: rules + LLM extraction, verbatim quotes, normalized keys, updates/deletions; `text.py` quote helpers
- `memdiag/judge.py` every model call: `Judge.ask` (cache, JSON retry, usage), `OpenAICompatJudge`, `FakeJudge` for tests
- `memdiag/prompt.py` + `memdiag/prompts/*.txt` versioned prompts (id/version header, `$field` placeholders)
- `docs/ROADMAP.md` plan; `docs/STABILITY.md` public names; `docs/metrics.md` metric definitions; `docs/RELEASING.md`
- `docs/plans/M<n>.md` the plan for each milestone from M2 on, written before its code

## Non-negotiables
- The core has zero runtime dependencies (stdlib only). Optional extras are fine; the core must not import them.
- Every Finding carries its failing turn, evidence turn(s), quotes and detector version (schema lands in M2; the legacy detectors migrate there).
- Every metric has an explicit denominator documented in `docs/metrics.md`. A metric with zero opportunities is `None`, never 1.0.
- Names in `docs/STABILITY.md` change only in a PR that edits that file and says why.
- Run rules before any LLM call. Do not add an LLM call where a rule suffices.
- Ledger items and judge verdicts need a quote that appears verbatim in the source; otherwise drop them or mark them unverified.
- All model calls go through `memdiag/judge.py`; nothing else does HTTP. Tests never call a live model: use `FakeJudge`.
- Prompts live in `memdiag/prompts/` with an id and version. Bump the version on any edit (the cache keys on it).
- Known extractor misses are `xfail` in `tests/test_known_limits.py`. Don't delete them to get a green suite.
- Demo and experiment data are synthetic or small. Never present them as benchmark results.
- Targets in the roadmap are pre-registered. Report a miss with its number; never move the target or tune on the held-out split.
- Never commit raw WildChat or other PII-bearing transcripts, or API keys.

## Workflow
- At the start of each milestone, update the instruction files first (this file, the roadmap, `docs/plans/M<n>.md`) in their own commit.
- One branch and one PR per milestone. One logical commit at a time, never one big commit.
- The owner has authorized committing, opening PRs and rebase-merging once CI is green. Report after each merge.
- Before merging, run the `reviewer` subagent (`.claude/agents/reviewer.md`) on the diff and fix what it confirms.
- Never push tags, publish to PyPI, or enable `PUBLISH_TO_PYPI`; the owner does these. Ask before spending money, running untrusted downloaded code, or anything public.
- Use the session scratchpad for throwaway files.

## Gotchas (learned the hard way)
- LLM-extracted fact keys vary (`user|myself.city` vs `user.city`). Always go through `ledger.normalize_key`, or stale detection silently fails.
- The extractor links names to relations only through the known people passed in (`extract_facts` v2); a person never named with a relation stays under their name.
- A 7B judge misses easy re-asks. Rules decide where they fire; the judge may add or confirm, never veto.
- 7B judges answer open questions badly: they misread queries and claim a response used the context when it didn't. Ask one specific question per check.
- Benchmark gold judges are wrong in both directions. Hand-check gold before trusting it.
- `gh pr checks --watch` right after a push can report "no checks" before CI registers. Wait until the checks exist and pass before merging.
- Models wrap quotes in quotation marks; verify quotes with `ledger.quote_span`, never with `in`.
- `pip download --no-binary` runs the package's build backend; treat it as running untrusted code.
