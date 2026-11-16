"""memdiag run from the command line."""
import json

from memdiag.cli import main

STALE = [["maya", "user", "I live in Seattle."], ["maya", "user", "We just moved to Portland."],
         ["maya", "assistant", "Since you live in Seattle, try BECU."]]


def test_cli_run_writes_findings_and_report_and_gates(tmp_path, capsys):
    log = tmp_path / "log.jsonl"
    log.write_text("".join(json.dumps({"user_id": u, "session_id": "s", "ts": f"2026-03-01T10:0{i}:00", "role": r,
                                       "content": c}) + "\n" for i, (u, r, c) in enumerate(STALE)))
    html_path, jsonl = tmp_path / "r.html", tmp_path / "f.jsonl"
    assert main(["run", str(log), "--html", str(html_path), "--findings", str(jsonl)]) == 0
    findings = [json.loads(line) for line in jsonl.read_text().splitlines()]
    assert [f["type"] for f in findings] == ["STALE_FACT"] and findings[0]["failing_turn"] == 2
    assert "STALE_FACT" in html_path.read_text()
    assert "fact_currency" in capsys.readouterr().out
    assert main(["run", str(log), "--html", str(html_path), "--findings", str(jsonl),
                 "--fail-under", "fact_currency=0.9"]) == 1
    assert main(["run", str(tmp_path / "missing.jsonl")]) == 2


def test_findings_jsonl_holds_only_failures(tmp_path):
    rows = STALE + [["maya", "user", "I already told you, we moved!"]]
    log = tmp_path / "log.jsonl"
    log.write_text("".join(json.dumps({"user_id": u, "session_id": "s", "ts": f"2026-03-01T10:0{i}:00", "role": r,
                                       "content": c}) + "\n" for i, (u, r, c) in enumerate(rows)))
    out = tmp_path / "f.jsonl"
    assert main(["run", str(log), "--html", str(tmp_path / "r.html"), "--findings", str(out)]) == 0
    assert [json.loads(line)["type"] for line in out.read_text().splitlines()] == ["STALE_FACT"]


def _write(path, rows):
    path.write_text("".join(json.dumps({"user_id": u, "session_id": "s", "ts": f"2026-03-01T10:0{i}:00", "role": r,
                                        "content": c}) + "\n" for i, (u, r, c) in enumerate(rows)))


def test_cli_run_prints_each_finding_as_a_card(tmp_path, capsys):
    _write(tmp_path / "log.jsonl", STALE)
    main(["run", str(tmp_path / "log.jsonl"), "--html", str(tmp_path / "r.html"), "--findings", str(tmp_path / "f.jsonl")])
    out = capsys.readouterr().out
    assert "STALE_FACT · confidence 1.00 · maya · city" in out
    assert '  user, turn 1    "We just moved to Portland."' in out  # evidence first, then the failing turn
    assert '  agent, turn 2   "Since you live in Seattle, try BECU."' in out


def test_cli_run_says_silence_is_not_proof(tmp_path, capsys):
    _write(tmp_path / "log.jsonl", [["maya", "user", "Hi there."], ["maya", "assistant", "Hello! How can I help?"]])
    main(["run", str(tmp_path / "log.jsonl"), "--html", str(tmp_path / "r.html"), "--findings", str(tmp_path / "f.jsonl")])
    out = capsys.readouterr().out
    assert "not proof of good memory" in out and "--model" in out


def _card(**kw):
    from memdiag import Event
    from memdiag.cli import finding_card
    f = {"type": "STALE_FACT", "location": None, "confidence": 1.0, "user_id": "b", "attribute": "city",
         "evidence_turns": [0], "evidence_quote": "I live in Denver.", "failing_turn": 2, "failing_quote": "x",
         "expected": "", "got": "", **kw}
    events = [Event.from_dict({"user_id": u, "session_id": "s", "ts": f"2026-03-01T10:0{i}:00", "role": r, "content": c}, i)
              for i, (u, r, c) in enumerate([["a", "user", "I live in Denver."], ["b", "user", "I live in Austin."],
                                             ["b", "assistant", "x"]])]
    return finding_card(f, {e.index: e for e in events})


def test_card_names_another_users_turn_and_shows_turnless_evidence():
    assert '  user a, turn 0  "I live in Denver."' in _card(type="CROSS_USER_LEAK")
    assert '  evidence        "The Platinum card has no annual fee."' in _card(
        type="IGNORED_CONTEXT", evidence_turns=[], evidence_quote="The Platinum card has no annual fee.")


def test_card_clips_long_quotes_around_the_failing_value():
    quote = "Here is a long and friendly answer about parks, trails, opening hours and parking options, " * 2 + \
        "all close to Seattle."
    line = _card(failing_quote=quote, got="Seattle").splitlines()[-1]
    assert "Seattle" in line and line.startswith('  agent, turn 2   "...') and len(line) < 120
