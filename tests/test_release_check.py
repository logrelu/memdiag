import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "release_check", Path(__file__).resolve().parent.parent / "scripts" / "release_check.py")
rc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rc)


def _repo(tmp_path, version="1.2.3", changelog="# Changelog\n\n## Unreleased\n- wip\n\n## 1.2.3\n- shipped\n- more\n\n## 1.2.2\n- old\n"):
    (tmp_path / "memdiag").mkdir()
    (tmp_path / "memdiag" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    (tmp_path / "CHANGELOG.md").write_text(changelog)
    return str(tmp_path)


def test_matching_tag_passes_and_writes_only_that_section(tmp_path):
    root, notes = _repo(tmp_path), tmp_path / "notes.md"
    assert rc.main(["v1.2.3", "--root", root, "--notes", str(notes)]) == 0
    assert notes.read_text() == "- shipped\n- more\n"


def test_tag_must_match_version(tmp_path, capsys):
    assert rc.main(["v1.2.4", "--root", _repo(tmp_path)]) == 1
    assert "does not match" in capsys.readouterr().err


def test_missing_changelog_section_fails(tmp_path, capsys):
    root = _repo(tmp_path, changelog="# Changelog\n\n## Unreleased\n- wip\n")
    assert rc.main(["v1.2.3", "--root", root]) == 1
    assert "no '## 1.2.3' section" in capsys.readouterr().err


def test_prerelease_version(tmp_path):
    root = _repo(tmp_path, version="1.2.3rc1", changelog="## 1.2.3rc1\n- candidate\n")
    assert rc.main(["v1.2.3rc1", "--root", root]) == 0


def test_repo_version_is_single_sourced():
    assert rc.package_version() == __import__("memdiag").__version__


def test_similar_heading_is_not_matched(tmp_path):
    root = _repo(tmp_path, changelog="## 1.2.3-beta\n- not this one\n")
    assert rc.main(["v1.2.3", "--root", root]) == 1
