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

## Held-out results, run `m6c` (2026-11-18, commit 4a9b7b2)
Full tables: `docs/validation.md`. 225 held-out cases: 100 injected, 100 paired controls, 25 history controls.

| Type | m6b | **m6c** | Target |
|---|---|---|---|
| `STALE_FACT` | 0.04 (1/25) | **0.92 (23/25)** | met |
| `RECALL_MISS` | 0.80 (20/25) | **0.80 (20/25)** | miss |
| `CONSTRAINT_DROP` | 1.00 | 1.00 (25/25) | met |
| `USER_REPAIR` | 1.00 | 1.00 (25/25) | met |
| All | 0.71 (71/100) | **0.93 (93/100)** | |

- **Exact turn:** 94/100. Every type meets ≥ 0.80; `RECALL_MISS` is exactly 0.80 (20/25), and `STALE_FACT`
  is 0.96 (24/25), above its recall because its one cancelled case has the finding on the gold turn.
- **False positives:** 3/125 overall (0.024). Per type, `STALE_FACT` is 3/50 (0.06), **a miss** against ≤ 0.05;
  the history controls alone are 1/25.
- **Flip rate:** 0/72 over the first run and 3 uncached reruns, with the new verdict (any change in the turns
  with a finding of the case's type). Met.
- **Cost:** 383.8 calls per 100 sessions. Every extraction was cached from earlier runs, so this run timed no
  extraction and gives no time estimate. The extraction prompt is unchanged since `m6b`, which measured
  about 114 minutes per 100 sessions on the same machine.
- **Goal 1 is not met:** `RECALL_MISS` recall 0.80 and `STALE_FACT` false positives 0.06.

### Diagnosis (read from cached outputs; nothing tuned)
- **`RECALL_MISS`: all 5 misses are the blind-written `r_c5`,** "Remind me, which city do you call home right
  now?". Neither the rules nor the judge read it as a re-ask. The template it replaced (`r_c4`) also began
  "Remind me…", and the judge missed that too, so "remind me" re-asks look like a real 7B blind spot.
- **`STALE_FACT` misses and false positives all come from the base sessions, not policy D:**
  - `stale_fact-heldout-006`: the extractor ledgered a birthday trip to Paris as the user's city, so the reply
    "mentions the current value" and the stale Toronto mention is excused.
  - `stale_fact-heldout-009`: the extractor ledgered a hotel ("Conrad Denver Downtown") as the user's employer.
    The real employer then counts as old, so the control ("moving from Spotify to Atlassian") fires on the gold
    turn and cancels the positive. That is 1 of the 3 false positives.
  - The other 2 false positives are the `m6b` background finding (Target the store, turn 13 of
    `stale_fact-heldout-001`), on its paired and history controls.
- **The blind history decoys produced no false positive of their own.** The cue list held on phrasings it was
  not written for.
- **The cost estimate was wrong at first.** The old method charged every call at the mean uncached time; here
  only 27 judge calls (~24 s each) were uncached, and 1476 cached extractions were charged at that rate. Fixed
  (per-role means, none when unmeasured), and the `m6b` and `m6c-dev` estimates were recomputed from their
  recorded usage: 119 -> 114 and 127 -> 123 minutes per 100 sessions.

### Review after the run (detector version 4)
The reviewer found three bugs in the v3 history check, each with a concrete reply:
- **The cue list was too loose.** A cue anywhere in the sentence counted, so "Spend some time in Seattle parks"
  and "Turn left on Pike St … Seattle coffee" were excused.
- **A cue on one old value excused another.** Only the last old value mentioned was checked.
- **A cue across a semicolon counted.** The history check split sentences differently from `mentions`.

v4 requires a cue before the old value in the same clause (or "anymore" after it), checks every old value,
and splits like `mentions`. Bare "left", "leaving", "time/days in" and "any more" are gone. Every v4 cue
also counted in v3, so v4 drops a subset of what v3 dropped: it keeps every v3 finding and may add more.
- **Dev (`m6c-dev-v4`):** every one of the 360 cases has the same findings as under v3.
- **Held-out is not rerun.** This milestone allows one held-out attempt, and the v4 tests were written after
  the held-out templates had been read. Run `m6c` stands as measured with v3. For v4, held-out recall is at
  least 0.92 by construction; its held-out false-positive rate is unmeasured until the next held-out run.

### Decision
- **Policy D ships** (rules decide stale findings, the judge only confirms), with the v4 history check. It is the default.
- **Run `m6c` is published as measured,** next to `m6b`. No second held-out attempt.

## Tests (no dataset, no model)
- A judge `uses_old: false` no longer drops a stale finding; `true` with a verbatim quote confirms it at 0.9.
- A history cue in the old value's sentence drops the candidate; a cue in another sentence does not.
- The new city re-ask pattern fires on "Which city are you in?" and not on "Which city are you visiting?".
- The template change was checked on the rebuilt suite, not in a unit test (it needs the dataset): 30 cases
  changed, the 25 held-out history controls and the 5 held-out re-asks in `r_c4`'s slot.
- Cost: each role is charged at its own mean uncached time, and a role with no uncached calls gives no estimate.

## Next
- **Background stale errors:** trips and hotels ledgered as the user's city or employer, and a store that
  shares the old employer's name. Measure extraction precision on dev first.
- **"Remind me" re-asks:** a held-out miss twice. Any fix retires `r_c5` from held-out, with a blind replacement.
- Link a name to its relation from the fact's own quote ("My daughter Ava is 10" -> `daughter` is Ava), so
  a re-ask by name fires on dev child_age. Dev only; held-out phrasings stay untouched.
