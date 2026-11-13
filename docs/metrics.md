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
| `fact_currency` | stale assertions | assertions about an attribute the user had changed at least once |
| `deletion_compliance` | forget requests the agent later violated (counted once per user and fact) | forget requests |
| `user_isolation` | assertions using another user's value | assertions about attributes another user also has |
| `groundedness` | assertions of a fact nobody stated | all asserted facts |
| `recall_continuity` | assistant turns that re-ask for a fact the user already gave (one per turn) | assistant turns where the user had already given a fact the rules can spot a re-ask for (city, employer, income, credit score) and hadn't deleted it |

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
