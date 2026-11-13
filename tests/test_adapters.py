from pathlib import Path

import pytest

from memdiag import run
from memdiag.adapters import convert, detect_format, load, read_records

FIX = Path(__file__).parent / "fixtures"


def test_openai_messages_become_events_and_findings():
    events = load(FIX / "openai_messages.jsonl")
    assert [e.role for e in events] == ["user", "assistant"] * 3  # system message dropped
    assert events[1].content == "Thanks, noted."  # list-of-parts content flattened
    assert events[5].memory == [{"id": "m1", "text": "User lives in Seattle."}]
    assert [e.index for e in events] == list(range(6))
    (f,) = [f for f in run(events)["findings"] if f["type"] == "STALE_FACT"]
    assert (f["failing_turn"], f["evidence_turns"]) == (5, [2])


def test_longmemeval_item_keeps_session_ids_and_dates():
    events = load(FIX / "longmemeval_mini.json")
    assert [e.session_id for e in events] == ["s_a", "s_a", "s_b", "s_b", "question"]
    assert events[2].ts.isoformat() == "2023-05-20T18:30:00"
    assert events[-1].content == "Which city do I live in now?" and events[-1].role == "user"
    assert all(e.user_id == "mini_1" for e in events)


def test_events_format_round_trips():
    rows = [{"user_id": "u", "session_id": "s", "ts": "2026-01-01T00:00:00", "role": "user", "content": "hi"}]
    (e,) = convert(rows)
    assert (e.user_id, e.role, e.content, e.index) == ("u", "user", "hi", 0)


def test_auto_detect_and_errors():
    assert detect_format(read_records(FIX / "openai_messages.jsonl")[0]) == "openai"
    assert detect_format(read_records(FIX / "longmemeval_mini.json")[0]) == "longmemeval"
    with pytest.raises(ValueError, match="Unrecognized log format"):
        detect_format({"foo": 1})
    with pytest.raises(ValueError, match="Unknown format"):
        convert([{"messages": []}], fmt="langfuse")
    assert convert([]) == []


def test_cli_reads_openai_logs_and_rejects_unknown_ones(tmp_path, capsys):
    from memdiag.cli import main
    out = tmp_path / "r.json"
    assert main(["diagnose", str(FIX / "openai_messages.jsonl"), "--json", str(out), "--no-color"]) == 0
    assert "STALE_FACT" in out.read_text()
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"foo": 1}\n')
    assert main(["diagnose", str(bad)]) == 2
    assert "Unrecognized log format" in capsys.readouterr().err
