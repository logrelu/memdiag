# Experiments

Small runs that informed the roadmap. **They are smoke tests, not benchmark results:** 2 to 4 cases
each, one local 7B model playing every role. Read the printed prompts and outputs; don't quote the numbers.

| Notebook | What it shows | Data |
|---|---|---|
| `blackbox_walkthrough.ipynb` | The black-box method step by step on 4 synthetic calls: logs to call records, rule symptoms, LLM fact extraction with verbatim quotes, the latest-value reference, context relevance and conflicts, sufficiency and use judging, retrieve/use location, scores with denominators, then a comparison with hidden gold. | Synthetic, inline |
| `longmemeval_toy.ipynb` | The same idea on 2 real LongMemEval-S questions (a knowledge update and a single-session fact) × 2 toy memory systems (BM25 top 3, last 2 sessions). | LongMemEval-S cleaned (MIT), downloaded to `data/` |

## Running them

```bash
ollama serve &               # local OpenAI-compatible endpoint
ollama pull qwen2.5:7b       # about 4.7 GB; qwen2.5:3b also works (MEMDIAG_MODEL=qwen2.5:3b)
pip install -e ".[dev]" nbconvert ipykernel
cd experiments && jupyter nbconvert --to notebook --execute --inplace blackbox_walkthrough.ipynb
```

`longmemeval_toy` downloads 277 MB once and builds a fact ledger with about 40 LLM calls per question.
That took about 25 minutes per question on a 16 GB M-series Mac. Ledgers are cached in `data/`.

## What they taught us (see `docs/ROADMAP.md`)

Last run 2026-11-13 with `qwen2.5:7b`, temperature 0, seed 0. Both reruns reproduced the earlier outputs exactly.

**Walkthrough (4 synthetic calls):** detection agreed 2/4 and location 1/2.
- **s4, correct.** The stale "Denver" context was flagged as a **retrieve** failure.
- **s5, missed.** The response re-asked Maya's age and interests, but the use-judge said it "used dinosaurs".
- **s7, false alarm.** The sufficiency judge read "good BBQ in town?" as needing BBQ facts, not the user's city.
- **The stale-fact check didn't work.** The extractor produced the keys `usermyself.city` and `user.city`, so Denver and Austin never ended up under the same fact. Key normalization is needed (M4).
- **Quotes aren't reliable.** 3 of 4 judge quotes were not in the context. Verbatim-quote checks would catch this (D5).
- **The rule layer has gaps.** It caught "I already told you!" but not "We moved to Austin, remember?".

**LongMemEval toy (2 questions × 2 memory systems):** detection agreed 3/4, and location agreed 2/2 on gold-wrong answers.
- **Mortgage, BM25.** The gold judge marked this correct, but the response treats the older $350,000 value as current. memdiag failed it at **use**, which looks right on reading. The judge's stated reason was garbled, though. The gold judge being lenient is the reason for D13.
- **Both recent-only failures** were correctly placed at **retrieve**, matching the LongMemEval evidence sessions.
- **The 7B extractor captured both mortgage values** ($350,000, then $400,000). The 3B extractor did not.
