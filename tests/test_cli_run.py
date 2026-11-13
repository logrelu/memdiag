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
