

https://github.com/user-attachments/assets/9e0d56b5-6cf2-44fc-9ecf-4d43a656f8b7

# memdiag

**Memory diagnostics for AI agents.** Point it at your agent's conversation logs and it tells you:

1. **Is it a memory problem or a retrieval problem?** Every agent answer is checked against a reconstructed timeline of what each user actually said, and against the documents the agent retrieved.
2. **Which memory approach would fix it?** Each user's history is replayed through candidate memory strategies, scored on whether they would have recalled the user's *current* facts.

No integration, no memory framework required. It reads logs you already have, offline.

```bash
pip install .            # no dependencies
memdiag demo --html report.html
memdiag diagnose traces.jsonl --docs docs.jsonl --html report.html --json report.json
```

## Input

`traces.jsonl`: one message per line.

```json
{"user_id": "maya", "session_id": "m3", "ts": "2026-03-02T12:00:06", "role": "assistant",
 "content": "Since you live in Seattle, BECU is a popular credit union near you.",
 "retrieved": [{"id": "doc_platinum", "text": "..."}], "context_tokens": 2600}
```

`retrieved` and `context_tokens` are optional. `docs.jsonl` (optional) is your knowledge base: `{"id": ..., "text": ...}`.

## What it detects

| Class | Failure | How it's detected |
|---|---|---|
| Memory | Stale memory | Agent asserts a value the user later updated |
| Memory | Failed deletion | Agent uses a fact after the user asked to forget it |
| Memory | Cross-user leak | Agent asserts a value that belongs to a different user |
| Memory | Invented memory | Agent asserts a user fact nobody ever stated |
| Memory | Forgotten memory | Agent asks again for a fact the user already gave |
| Retrieval | Ignored context | Agent's answer contradicts a document it retrieved |
| Retrieval | Retrieval miss | Agent was unsure or the user pushed back, and a better document existed but wasn't retrieved |
| Context | Context overload | A failure happened with a very large context window (tagged) |
| Unknown | Unattributed | User pushed back and no rule explains it |

User pushback ("that's wrong", "I asked you to forget") is used as a failure signal.

## Strategy replay

Candidate strategies today: no memory, full history in context, top-k search (per user and shared index), latest-value profile, and profile with deletion. Real backends plug in by implementing `MemoryBackend` (`add`, `recall`) in `memdiag/strategies.py` and replaying the same history.

## MCP server

```bash
pip install ".[mcp]"
memdiag-mcp            # stdio server with tools diagnose_traces and diagnose_report
```

## Limits of v0

- Extraction is rule-based: location, employer, income, loans and credit score. The `RuleExtractor` interface is where an LLM extractor plugs in to cover arbitrary facts.
- The demo data is synthetic.
- Vendor adapters (Zep, Mem0, graph stores) are not built yet; only the interface exists.

### Known failure on unseen phrasing

`examples/unseen_phrasing.jsonl` contains two real memory failures (a stale city and a stale employer) that v0 misses, because the user says "we relocated to" and "I left Target for a role at REI". When extraction misses an update, the strategy replay is graded against an incomplete timeline and can overrate strategies like full history. `tests/test_known_limits.py` records this as expected failures; the LLM extractor is the fix.
