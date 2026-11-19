# M6c: rules decide stale findings, fresh held-out decoys, a full dev sample

Follows `docs/plans/M6b.md`. Branch `m6c`, one PR. Goal 1 targets are unchanged.

## Why
In run `m6b`, held-out `STALE_FACT` recall was 0.04 (1/25). The ledger and the mention check found the
candidates; the judge then vetoed them. Policies A (v1 veto) and C (v2 "veto with evidence") both let a 7B
judge drop a rule hit, which breaks the CLAUDE.md rule for re-asks. `RECALL_MISS` was 0.80 (20/25); all 5
misses were one held-out phrasing, "Remind me which city you're in?" (`r_c4`).

## 1. Policy D: rules decide, the judge confirms
- A reply that mentions an old value of an updated fact, and not the current one, is a candidate (unchanged).
- **The candidate is dropped only by a rule:** the sentence that mentions the old value carries a history cue
  ("used to", "back when", "since you left", "moved from", "former", "no longer", ...). The cue list is
  general English for talking about the past. It is written from the dev templates and frozen in its own
  commit before the new held-out templates exist (section 3).
- **The judge can only confirm.** `check_stale` v1 is asked as today. `uses_old: true` with a verbatim quote
  raises confidence to 0.9 (`ledger.stale_mention+llm`). Any other answer leaves the finding at 0.5
  (`ledger.stale_mention`). No judge answer removes a finding.
- `DETECTOR_VERSION` goes to 3.

## 2. `RECALL_MISS`: one general city pattern
The user-city re-ask pattern also matches "which city" and "you're in" ("Which city are you in?", "remind me
what city you're in"). This change comes from a held-out miss, so `r_c4` is retired from held-out (section 3).

## 3. Retired and new held-out templates
Templates that informed a fix are retired from held-out: `c_h3` and `e_h2` (the cue list was written after
seeing them) and `r_c4` (the pattern above).
- Replacements are written **blind**: a subagent gets the template spec (slot, placeholders, what the reply
  must do) and is told not to read `memdiag/` or any results. Its output is committed unedited, after the cue
  list and the pattern are committed.
- History controls: 2 new held-out city and 2 new held-out employer templates. Re-asks: 1 new held-out city
  template, in `r_c4`'s slot, so the main RNG draws the same and every other case stays byte-identical.
- History controls are built from their own RNG, so new history templates change only `-hist` cases.

## 4. Choice on dev, then held-out once
- **Dev sample:** all 40 dev positives per type, with their 40 paired controls, plus 40 `STALE_FACT` history
  controls, `qwen2.5:7b`.
- **Selection rule (fixed now):** ship D if dev `STALE_FACT` recall is ≥ 0.85 and dev false positives (paired
  and history controls together) are ≤ 0.05. If D misses on dev, only the cue list may change, on dev only,
  and every attempt is recorded in this file.
- **Held-out:** the full held-out LLM run once, named `m6c`, next to `m6b`. Then 3 uncached reruns on the
  same 72 cases as `m6b` (first 8 positives per type, with controls), with the flip verdict defined in M6b
  (any change in the turns with a finding of the case's type). The rules-mode run is redone too.
- A miss is published with its number. There is no second held-out attempt in this milestone.

## Dev results, run `m6c-dev` (2026-11-18)
All 40 dev positives per type, their paired controls and 40 history controls: 360 cases, `qwen2.5:7b`.

| Type | Recall | FP |
|---|---|---|
| `STALE_FACT` | 40/40 | 2/80 (paired 1/40, history 1/40) |
| `RECALL_MISS` | 28/40 | 0/40 |
| `CONSTRAINT_DROP` | 40/40 | 0/40 |
| `USER_REPAIR` | 40/40 | 0/40 |

- **D meets the selection rule** (recall 1.00 ≥ 0.85, FP 0.025 ≤ 0.05) on its first attempt. The cue list was
  not changed. Held-out runs next.
- **Both stale false positives are one background finding:** turn 15 of `stale_fact-dev-015`, where the
  extractor ledgered `user.city` as "parents' place", then "Virginia", and a later reply mentions Virginia. It
  appears on the positive too, so net recall is unaffected.
- **`RECALL_MISS` child_age is 1/13 on dev.** In "My daughter Ava is 10." the extractor records
  `daughter.age` but not the name, so "How old is Ava?" doesn't name a known person and the rule can't fire;
  the judge misses it too. The held-out child_age re-ask ("How old is your daughter now?") names the relation,
  so this is a dev-only gap. It is not fixed in this milestone (the plan allows only cue changes after the dev
  run); see Next.

## Tests (no dataset, no model)
- A judge `uses_old: false` no longer drops a stale finding; `true` with a verbatim quote confirms it at 0.9.
- A history cue in the old value's sentence drops the candidate; a cue in another sentence does not.
- The new city re-ask pattern fires on "Which city are you in?" and not on "Which city are you visiting?".
- New templates leave every non-history case byte-identical except the `r_c4` slot.

## Next
- Link a name to its relation from the fact's own quote ("My daughter Ava is 10" -> `daughter` is Ava), so
  a re-ask by name fires on dev child_age. Dev only; held-out phrasings stay untouched.
