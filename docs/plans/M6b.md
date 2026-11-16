# M6b: stale-fact judge policy, the full LLM run and the flip rate

Follows `docs/plans/M6.md`. Branch `m6b-stale-judge`, one PR. Goal 1 targets are unchanged.

## Why
In the first LLM run, all 3 `STALE_FACT` misses had a correct ledger and a correct candidate. The 7B
`check_stale` judge then vetoed them (`uses_old: false` for "Near you in Portland, there are good options").
The suite could not show what the veto buys: every stale control mentions the current value, so no control
ever produced a stale candidate for the judge to reject.

## 1. A control the judge has to reject (written before any run of it)
New `STALE_FACT` **history controls**. The reply mentions only the old value, as past history, so the
mention check produces a candidate and only the judge (or a rule) can stop it. There is one per stale case,
with case id `<stale case>-hist`. A separate RNG is seeded from the case id, so every existing case stays
byte-identical, and the first run's results stay comparable.

| id | split | text |
|---|---|---|
| `c_h1` | dev | Since you left {old}, here is a tip. |
| `c_h2` | dev | Back when you lived in {old}, you mentioned the rain. |
| `c_h3` | heldout | After leaving {old}, settling in somewhere new takes time. |
| `e_h1` | dev | Now that you're done with {old}, check your new benefits. |
| `e_h2` | heldout | Your years at {old} should help in the new role. |

History controls count toward the `STALE_FACT` false-positive rate. They are also reported on their own
row, so they don't dilute the existing controls.

## 2. Candidate policies, chosen on dev only
- **A. veto** (today): `check_stale` v1 has to say `uses_old: true` and quote the reply, or the candidate is dropped.
- **B. no judge:** every candidate stands at confidence 0.5. This is the recall ceiling, and the history
  controls show its cost.
- **C. specific question:** `check_stale` v2 asks one narrower question: is the old value presented as the
  user's *current* situation, or as past history? The answer is
  `{"presents_as": "current" | "past" | "not_about_user", "quote": ...}`. Only `past` and
  `not_about_user` with a verifiable quote can drop a candidate. An unparseable or unquoted answer keeps the
  candidate at 0.5 (the judge confirms, and vetoes only with evidence).

**Selection rule (fixed now):** pick the policy with the highest dev `STALE_FACT` recall whose dev
false-positive rate, history controls included, is ≤ 0.05. Ties go to the simpler policy. The dev numbers
for every policy go in this file. Held-out is run once, with the chosen policy.

## 3. The full held-out LLM run, the flip rate and the cost
- All held-out cases (25 positives and 25 controls per type, plus 25 history controls), `qwen2.5:7b`.
- Flip rate: 3 uncached reruns on the held-out cases, with the shipped settings (temperature 0, seed 0).
  - At those settings the flip rate measures the nondeterminism users actually get (server batching,
    floating point), not sampling variance. The report says so.
  - A case flips if its verdict differs between the original run and any rerun.
- Runtime, judge calls and tokens per 100 sessions are recorded in the run metadata (Goal 1, criterion 5).

## Reporting
- Results get a run name: `validation/results/goal1_<mode>[_<run>].json`. The first LLM run stays as it is,
  and the new run is reported next to it, not instead of it.
- If the chosen policy misses a target on held-out, the miss is published with its number. There is no
  second held-out attempt in this milestone.

## Tests (no dataset, no model)
- History controls are built with the old value present and the new value absent, and they don't change
  existing cases.
- Policy C: `past` with a verifiable quote drops the candidate, `current` confirms it at 0.9, and a missing or
  unverifiable quote keeps it at 0.5.
- The flip rate counts a case as flipped when any run differs; the result file name carries the run name.
