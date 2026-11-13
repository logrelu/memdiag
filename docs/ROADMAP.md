# Roadmap

Status: active plan, updated 2026-11-12. Numeric targets are pre-registered bars, not standards. If a
target is missed, the miss is reported; the target is not moved.

## Goal

Be to agent memory what RAGAS is to RAG: point memdiag at the logs an agent already writes, and get
back **every memory failure, located at the turn where it happened, with the earlier turn it
contradicts, quoted**. Ship the metric with published numbers on how often it is right.

## Why this, and not another retention score

- **The basic metric already exists.** DeepEval, MLflow and Opik all ship a metric called
  "KnowledgeRetention". LangSmith, Phoenix and Opik run an LLM judge over a whole session. Each of
  these returns one score per session and a free-text reason.
- **The memory benchmarks share the same gaps** (survey, 2026-11): Redis, Mem0, Zep, Prosus MemEval
  and Supermemory all grade QA answers against gold with an LLM judge. None works without ground
  truth, none locates where a failure happened, and none checks its judge against humans. They also
  dispute each other's numbers (Zep and Mem0 on LoCoMo; Supermemory's "~99%").

What nobody ships, and what memdiag will:

1. **Findings that point at a turn.** Each Finding names the failing turn, the evidence turn, both
   quotes, and the failure type. Session scores are computed from Findings, never the reverse.
2. **A ledger that tracks updates and revocations.** It records what the user said and when, which
   facts were later replaced, and which instructions were withdrawn. Without it, detectors flag
   legitimate changes as failures.
3. **Failure location when the memory context is logged.** A failure is either **retrieve** (the
   memory layer didn't supply the fact) or **use** (the fact was in context and the model ignored it).
   QA benchmarks can't make this split.
4. **Published validation:** mutation-test recall and failing-turn accuracy, false positives on
   negative controls, Cohen's kappa against human labels, and how often the judge changes its answer
   on a rerun. This is where RAGAS was weakest, so we lead with it.

## Design decisions

| # | Decision | Why |
|---|----------|-----|
| D1 | The unit of output is a `Finding`: type, failing turn, evidence turn(s), quotes, detector version. | Localization is the product. |
| D2 | One ledger of user facts and constraints (with source quotes, replacements and revocations) serves both scopes. | In-session and cross-session memory reuse the same detectors. |
| D3 | Rules run first, and an LLM is called only for plausible (item, turn) pairs. | Cheaper and more precise. Our runs showed 7B judges misreading queries when asked open questions. |
| D4 | Judge prompts ask one specific question per check ("Does turn 9 ask for the order number the user gave at turn 2?"). | MultiChallenge reports 94% human agreement for rubric-style judging against 37% for judging the raw conversation. |
| D5 | A ledger item or judge verdict needs a quote that appears verbatim in the source; otherwise it is dropped or marked unverified. | Our 7B judge gave a quote that wasn't in the context in 3 of 4 calls. |
| D6 | The judge is an open-source local model behind an OpenAI-compatible endpoint (Ollama, vLLM, llama.cpp). Hosted models are optional. | Free and reproducible without an API key. Reference machine: 16 GB Mac, `qwen2.5:7b`. |
| D7 | The core is stdlib-only, with no pydantic or httpx. | `pip install memdiag` must stay instant and safe. This overrides the helper plans. |
| D8 | Judge calls are cached on disk, keyed by prompt id and version, model, and inputs. Tests use a FakeJudge and never a live model. | Reruns are free and the validation numbers can be reproduced. |
| D9 | The judge's model family differs from the model that generated the responses, or the report warns. | Avoids self-preference bias. |
| D10 | Scores are in [0, 1], higher is better, shown with counts and denominators. A score with no opportunities is `None`. | Same convention as `metrics.py` today. Signals such as `repair_count` are reported as counts. |
| D11 | Names in `docs/STABILITY.md` are frozen when v0.2.0 ships. Renames after that get an alias for two minor versions. | Breaking renames cost RAGAS users' goodwill. |
| D12 | Validation starts with mutation tests, then public benchmarks, then human labels. | Mutation tests are cheap, run locally and give exact labels. Humans are the slowest step. |
| D13 | The gold labels from benchmark judges are checked by hand before use. | In our runs the LongMemEval-style judge was wrong in both directions. |

## Failure taxonomy (stable IDs)

| Type | Meaning | Scope | Ships |
|---|---|---|---|
| `RECALL_MISS` | Re-asks for a fact the user gave (mode `reask`), or acts as if it was never given (mode `ignored`). | both | v0.2 |
| `STALE_FACT` | Uses a value the user later replaced. | both | v0.2 |
| `CONSTRAINT_DROP` | Breaks an instruction that is still in force (rule-checkable ones first). | in-session | v0.2 |
| `USER_REPAIR` | The user repeats or corrects themselves ("I already told you"). Reported as a signal that adds confidence to other findings, not as a score. | both | v0.2 |
| `HALLUCINATED_MEMORY` | States a user fact the user never gave. | both | v0.2 (exists as a rule today) |
| `DELETION_VIOLATION` | Uses a fact the user asked to forget. | cross-session | exists (rules); LLM later |
| `CROSS_USER_LEAK` | Uses another user's fact. | cross-session | exists (rules) |
| `SELF_CONTRADICTION`, `TOOL_RESULT_FORGOTTEN`, `MEMORY_INTRUSION` | Contradicts itself; ignores a tool result; injects an irrelevant memory. | — | later |

Context length and compaction are **covariates** (token distance, cumulative tokens, `after_compaction`),
not finding types.

## Observability tiers

- **L0 transcript only:** all in-session types, plus `USER_REPAIR`.
- **L1 adds `user_id` across sessions:** `RECALL_MISS`, `STALE_FACT` and `HALLUCINATED_MEMORY` across sessions, with the ledger built from earlier sessions.
- **L2 adds the injected memory context per call:** retrieve-vs-use location, context precision, conflicts within the context.
- **L3 adds the memory store's reads and writes:** write-quality checks and replay. Later.

## Milestones (one branch, one PR each; instruction files updated first)

| M | PR | Exit criterion |
|---|----|----------------|
| M0 | Metrics, CI gate, release workflow | Done: PRs #1, #2 |
| M1 | Instruction files: this roadmap, `CLAUDE.md`, `STABILITY.md`, reviewer agent (a test-running Stop hook is left to the owner to add) | Done: PR #3 |
| M1b | `experiments/`: LongMemEval toy and black-box walkthrough notebooks | Done: PR #5 |
| M2 | Localized `Finding` fields on the existing `Event`/`Finding` types, `Event.memory`, and adapters: OpenAI messages, events JSONL, LongMemEval (`LedgerItem` moves to M4) | Done: PR #6 |
| M3 | Judge layer: OpenAI-compatible client, disk cache, versioned prompts in `memdiag/prompts/`, FakeJudge, time and token accounting | A cached rerun makes zero calls; tests make no network calls |
| M4 | Ledger: rule plus LLM extraction, verbatim-quote check, deterministic key normalization, replacements and revocations | 20 hand-written fixtures pass (updates, revocations, scope) |
| M5 | Detectors `RECALL_MISS`, `STALE_FACT`, `CONSTRAINT_DROP`, `USER_REPAIR`; retrieve/use location at L2; metrics; HTML report with failing and evidence turns side by side | `memdiag run log.jsonl` writes findings JSONL and `report.html` |
| M6 | **Goal 1 harness:** mutation suite built from MIT/CC-BY conversations, with negative controls and a held-out split | Goal 1 table generated by one command |
| M7 | External validity: MultiChallenge (per-axis kappa), LongMemEval (location against evidence sessions), 50-item hand audit | Goal 2 numbers in `docs/validation.md` |
| M8 | Integrations: OTel GenAI ingest and export, Langfuse score write-back, pytest `assert_memory` | One offline example per integration |
| M9 | Release v0.2.0 | Release 1 criteria met |

## Goal 1: memdiag finds memory failures at the right turn

**Test:** mutation testing. Start from clean conversations (LongMemEval sessions, MIT; MultiChallenge,
CC-BY), inject exactly one known failure at a known turn, and add negative controls that look like
failures but aren't: paraphrases, legitimate confirmations, user-requested changes and revocations. Templates
and source conversations are split 70/30, and prompts are tuned on the 70% only.

**Success criteria** (pre-registered; local `qwen2.5:7b` judge):

1. Detection recall ≥ 0.85 per shipped type, on the held-out 30%.
2. Exact failing-turn accuracy ≥ 0.80, counted only when the type is also right (RankJudge-style).
3. False-positive rate ≤ 0.05 on negative controls.
4. Flip rate ≤ 5% across 3 judge reruns.
5. Runtime and judge calls are reported per 100 sessions, and the whole suite runs on the 16 GB Mac.

## Goal 2: the findings agree with real labels

1. MultiChallenge: per-axis Cohen's kappa ≥ 0.61 against the rubric labels on shipped axes, with
   bootstrap 95% CIs. The rubric labels are themselves checked on a 50-item hand audit.
2. LongMemEval (L2): on wrong answers, retrieve vs use agrees with the gold evidence sessions ≥ 80%.
3. Human audit: kappa ≥ 0.61 between memdiag and the owner's labels on 50 or more items, with raw
   agreement and prevalence shown alongside.
4. Comparison: run DeepEval's KnowledgeRetention on the same labelled set and report its kappa next
   to ours.

## Release 1: v0.2.0

The first public release; there is no v0.1.0 tag, because names freeze here.

1. Goal 1 is met, or each miss is stated with its number in the release notes and the README.
2. The README opens with the validation table and a 30-second quickstart on a bundled sample log.
3. `pytest -q` and `ruff check .` pass on 3.10 to 3.12. The core has zero runtime dependencies.
4. `docs/STABILITY.md` is frozen. Every metric is in `docs/metrics.md` with its denominator.
5. A pre-release `v0.2.0rc1` has gone through the real tag-push release path.
6. A person who hasn't seen the repo gets a report on their own JSONL in under 15 minutes.

## What our own runs showed (experiments/, 2026-11)

| Finding | Consequence |
|---|---|
| The LongMemEval-style judge marked a correct "lavender gin fizz" answer wrong (3B) and passed a confused stale answer (7B). | D13: hand-check gold labels |
| The 7B use-judge said a response used the context when it had re-asked for it. The sufficiency judge misread a BBQ question. | D3/D4: one specific question per check |
| The LLM extractor produced keys like `user\|myself.city` and `user.city`, so Denver and Austin never collided and the stale fact went undetected. | M4: deterministic key normalization |
| 3 of 4 judge evidence quotes were not in the context. | D5: verify quotes |
| The 7B extractor took about 25 minutes per LongMemEval question of 40 sessions. | D3: rules and candidate filters first; extract once per user and cache |
| The rule layer missed "We moved to Austin, remember?" and "we relocated to Austin". | The LLM is needed, but behind rules |

## Open items and unverified leads

- The helper plans cite sources this repo hasn't checked: arXiv 2606.19544, 2609.38021 and 2605.21748;
  the Langfuse session-judge limits; OTel `gen_ai.conversation.compacted`. Verify each before citing it.
- Licenses: LongMemEval is MIT (checked). MultiChallenge is CC-BY-4.0 on Hugging Face, but disputed for
  the original repo. Lost in Conversation is MIT on GitHub and CDLA-Permissive-2.0 on Hugging Face.
  WildChat is ODC-BY and contains PII, so never commit raw WildChat transcripts.
- Papaya (YC) runs over production traces and claims 200+ failure checks. Its launch page doesn't say
  whether any are about memory.
