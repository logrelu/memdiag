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
- Flip rate: 3 uncached reruns, with the shipped settings (temperature 0, seed 0).
  - The reruns cover the first 8 positives per type on held-out, with their controls and history controls
    (72 cases). That is the same positives and controls as the first LLM run.
  - Rerunning all ~225 held-out cases 3 times would take over 12 hours on the reference Mac (Intel CPU, no
    GPU). This sample was chosen before any rerun.
  - At those settings the flip rate measures the nondeterminism users actually get (server batching,
    floating point), not sampling variance. The report says so.
  - A case flips if its verdict differs between the original run and any rerun.
- Runtime and judge calls per 100 sessions are recorded in the run metadata and the report (Goal 1, criterion 5). Cached calls are charged at the mean time of uncached ones, since a new user pays for every call.

## Reporting
- Results get a run name: `validation/results/goal1_<mode>[_<run>].json`. The first LLM run stays as it is,
  and the new run is reported next to it, not instead of it.
- If the chosen policy misses a target on held-out, the miss is published with its number. There is no
  second held-out attempt in this milestone.

## Tests (no dataset, no model)
- History controls are built with the old value present and the new value absent, and they don't change
  existing cases.
- Policy C: `past` with a verifiable quote drops the candidate, `current` confirms it at 0.9, and a missing or
  unverifiable quote keeps it at 0.5. These tests were removed with the revert to v1 (see Decision).
- The flip rate counts a case as flipped when any run differs; the result file name carries the run name.

## Dev results (first 12 positives per type on dev, with their 12 controls and 12 history controls)
`STALE_FACT` only, `qwen2.5:7b`, run 2026-11-16.

| Policy | Recall | Exact turn | FP, paired controls | FP, history controls | FP, all |
|---|---|---|---|---|---|
| A. veto (`check_stale` v1) | 12/12 | 12/12 | 0/12 | **6/12** | 6/24 (0.25) |
| B. no judge | 12/12 | 12/12 | 1/12 | 12/12 | 13/24 (0.54) |
| C. specific question (`check_stale` v2) | 12/12 | 12/12 | 1/12 | 1/12 | 2/24 (0.08) |
| C + value fix (below) | 12/12 | 12/12 | 0/12 | 0/12 | 0/24 (0.00) |

- **A's veto doesn't buy precision.** The v1 judge accepted half of the history controls ("Back when you lived
  in X") as stale. On dev it also never rejected a true positive. Its held-out misses (M6) were the opposite
  error, so v1 is unreliable in both directions.
- **C's two false positives were one background finding,** on turn 5 of the same base session (it appears in
  both the control and the history control). The extractor ledgered `caffeine_intake: coffee -> around 200mg`,
  and the reply "Medium coffee (200mg of caffeine)" states both. Two value bugs hid the current value:
  - the hedge "around" was read as part of the unit;
  - "200mg" didn't parse as a number.

  Both were fixed in general form, with tests. This is the only change made after looking at dev results.
- **Choice: C with the value fix.** It is the only policy with dev false positives ≤ 0.05 (0/24), and its
  recall equals the others. A sample of 12 per kind is small. The held-out run is the test.

## Held-out results, run `m6b` (2026-11-17, commit 59c8416)
Full tables: `docs/validation.md`. 225 held-out cases: 100 injected, 100 paired controls, 25 history controls.

| Type | Recall | Target |
|---|---|---|
| `STALE_FACT` | 0.04 (1/25) | miss |
| `RECALL_MISS` | 0.80 (20/25) | miss |
| `CONSTRAINT_DROP` | 1.00 (25/25) | met |
| `USER_REPAIR` | 1.00 (25/25) | met |
| All | 0.71 (71/100) | |

- **False positives:** 2/125 (met).
- **Flip rate:** 0/72 over the first run and 3 uncached reruns (met).
- **Cost:** about 390 model calls and 2 hours of CPU per 100 sessions on the reference Mac (Intel CPU, no GPU).
- **Goal 1 is not met.**
- **Run history.** The first attempt died on case ~21, when one extraction call ran past the 600 s timeout.
  The judge then got `max_tokens=1024`, and the run was restarted from the cache. Later the Mac slept once,
  and the stuck process was restarted the same way. No detector changed, and nothing was scored between
  attempts.
- **Machine.** The reference Mac: 16 GB, Intel i7-9750H, CPU only. The 145-minute wall time covers the main
  pass only; the reruns took about 8 more hours.
- **The flip verdict for this run** was a change in exact-turn hit (positives) or false positive (controls).
  Review found that it misses a positive whose non-gold findings change. From now on a flip is any change in
  the turns with a finding of the case's type. The m6b reruns weren't saved per case, so 0/72 stands under the
  old definition.

### Diagnosis (read from cached outputs; nothing tuned)
- **`STALE_FACT`: the v2 judge vetoed true positives.** The ledger and the mention check were right in every
  case read. The judge then answered `presents_as: "past"` for explicit stale uses: "Near you in Prague, there
  are good options" and "Your benefits through Target might cover this". It quoted the reply verbatim, so the
  quote check passed.
  - The 7B judge seems to answer whether the fact is still true (the user moved, so Prague is past), not how
    the reply presents it.
  - **A verbatim quote that contains the old value is not evidence of pastness.** Policy C's safeguard checked
    the wrong thing.
  - Once, the judge returned the prompt's own example ("as a Target resident") as its quote.
- **`RECALL_MISS`: all 5 misses are one held-out phrasing,** "Remind me which city you're in?" (`r_c4`).
  Neither the rules nor the judge read it as a re-ask. Every other held-out re-ask phrasing was caught.
- **False positives: both are one background finding.** At turn 13 of a base session, the reply mentions
  Target the store after the user left Target the employer. It appears in the control and the history control
  alike, and on the positive too, so net recall is unaffected.
- **Dev didn't predict held-out.** 12 dev cases per kind scored 12/12, but they used other phrasings. The
  selection sample was too small to expose a judge that keys on phrasing.

### Decision
- **v2 is not shipped.** The default stays `check_stale` v1 (the commit "Keep stale judge v1 as the default"). v2 also vetoes the README
  walkthrough's Denver finding.
- **The general fixes stay:** value matching, the answer cap, the history controls, named runs, the flip rate
  and the cost reporting.
- **Run `m6b` is published as measured,** next to the first LLM run. The run's commit, 59c8416 (before the
  rebase-merge), is kept on the remote branch `m6b-run-provenance`.

## Next (M6c)
**Rules decide stale findings; the judge may only confirm.** A mention of the old value without the current
one fires unless its sentence carries a history cue. The judge raises confidence and can't drop a candidate.
This follows the existing CLAUDE.md rule for re-asks, which policies A and C both broke.
- **New held-out history templates, written before the run.** The cue list is written after seeing this run's
  held-out decoys (`c_h3`, `e_h2`), so those two are retired from held-out and the report says so.
- **A larger dev sample** (all 40 per type) before choosing.
