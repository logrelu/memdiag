# Metrics

Every metric is a score in `[0, 1]` (higher is better) computed as

    score = 1 - failures / opportunities

and is always reported with both counts. A metric with zero opportunities is `null` / `n/a`:
the agent never had the chance to fail, which is not evidence it remembers well. A `--fail-under`
gate never fails on an `n/a` metric, so check `opportunities` before trusting a green gate.

"Asserted fact" means a user attribute the agent stated about the user ("since you live in
Seattle"), found by the extractor. Scores are only as complete as the extractor; see
[Limits](../README.md#limits-of-v0).

| Metric | Failures | Opportunities |
|---|---|---|
| `memory_faithfulness` | stale + deleted-fact + cross-user + invented assertions | all asserted facts |
| `fact_currency` | (reply, fact) pairs where the reply uses an old value of a fact the user updated: a stale rule assertion, or a mention of the old value without the current one (confirmed by the judge in `--model` mode) | (reply, fact) pairs where the reply mentions any value, old or current, of a fact the user had updated |
| `deletion_compliance` | forget requests the agent later violated (counted once per user and fact) | forget requests |
| `user_isolation` | assertions using another user's value | assertions about attributes another user also has |
| `groundedness` | assertions of a fact nobody stated | all asserted facts |
| `recall_continuity` | assistant turns that re-ask for a fact the user already gave (one per turn): by rule patterns, or by the judge in `--model` mode | assistant turns where the user had a live fact (not deleted) that can be checked: one with a re-ask pattern (city, employer, income, credit score, age, name, birthday, interest, job title), or any fact in `--model` mode |

`memory_faithfulness` and `groundedness` count only assertions the rules can read ("since you live in
Seattle"). A stale value the ledger finds as a plain mention ("Seattle weather is rainy") counts in
`fact_currency` and not in them, so their denominators stay assertions.

Signals, not scores: `repair_count` is the number of assistant turns followed by a user repair ("I already
told you"). A repair raises the confidence of memory findings on that turn by 0.25.

With `--model`, the run's `mode` is `llm`, `judge_model` names the judge, and `judge_usage` reports calls and
cache hits per role. Scores from different judges are not comparable.

## Using the scores

```python
from memdiag import run_files
res = run_files("traces.jsonl", "docs.jsonl")
res["metrics"]["deletion_compliance"]   # {"score": 0.5, "failures": 1, "opportunities": 2, ...}
```

```bash
# CI gate: exit 1 if any threshold is missed
memdiag diagnose traces.jsonl --fail-under deletion_compliance=1.0 --fail-under user_isolation=0.99
```

## Not yet measured

Retrieval failures (`ignored_context`, `retrieval_miss`) are still reported as findings but have no
normalized score. Scores do not yet carry confidence intervals; with small `opportunities` treat
them as counts, not rates.
