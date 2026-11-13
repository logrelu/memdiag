# Stability

Public names are an API. Names listed here as **frozen** never change. A rename after freezing ships the
new name and keeps the old one as an alias for two minor versions.

Status: **proposed**. Everything below freezes when v0.2.0 is released. Until then, a name changes only in
a PR that edits this file, and the PR description says why.

## Finding types

| Type | Status | Notes |
|---|---|---|
| `RECALL_MISS` | proposed | modes: `reask`, `ignored` |
| `STALE_FACT` | proposed | |
| `CONSTRAINT_DROP` | proposed | |
| `USER_REPAIR` | proposed | a signal; never a score on its own |
| `HALLUCINATED_MEMORY` | proposed | currently `hallucinated_memory` in `detect.py` |
| `DELETION_VIOLATION` | proposed | currently `failed_deletion` |
| `CROSS_USER_LEAK` | proposed | currently `cross_user_leak` |

Failure locations (L2 logs only): `retrieve`, `use`.

## Metrics

Scores are in [0, 1], higher is better, and come with `failures` and `opportunities`. A score with zero
opportunities is `None`.

| Metric | Status | Failures / opportunities |
|---|---|---|
| `fact_recall` | proposed (replaces `recall_continuity`) | `RECALL_MISS` / turns with a relevant earlier fact |
| `fact_currency` | proposed (exists) | `STALE_FACT` / turns that use a fact the user updated |
| `constraint_retention` | proposed | violations / (constraint, turn) pairs in scope |
| `groundedness` | proposed (exists) | `HALLUCINATED_MEMORY` / user-fact assertions |
| `deletion_compliance` | proposed (exists) | deletion requests violated / deletion requests |
| `user_isolation` | proposed (exists) | `CROSS_USER_LEAK` / assertions on attributes other users share |
| `memory_faithfulness` | proposed (exists) | any memory finding / user-fact assertions |
| `context_sufficiency` | proposed (L2) | calls whose context lacked a needed fact / calls with a needed fact |
| `context_use` | proposed (L2) | use failures / calls whose context was sufficient |
| `context_precision` | proposed (L2) | irrelevant injected memories / injected memories |

Reported as counts, not scores: `repair_count`, `memory_loss_onset` (turn index and cumulative tokens of the
first finding).

## Finding fields

`type`, `mode`, `failing_turn`, `evidence_turns`, `failing_quote`, `evidence_quote`, `item_id`, `location`,
`confidence`, `detector`, `detector_version`, `judge_model`, `prompt_version`, `covariates`.
