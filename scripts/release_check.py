"""Validate a release tag before publishing.

    python scripts/release_check.py v0.2.0 [--notes release_notes.md]

Fails (exit 1) unless the tag equals "v" + memdiag.__version__ and CHANGELOG.md has a
"## <version>" section. With --notes, writes that section's body for the GitHub Release.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def package_version(root: Path = ROOT) -> str:
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', (root / "memdiag" / "__init__.py").read_text(), re.M)
    if not m:
        raise SystemExit("error: __version__ not found in memdiag/__init__.py")
    return m.group(1)


def changelog_section(version: str, root: Path = ROOT) -> str | None:
    text = (root / "CHANGELOG.md").read_text()
    m = re.search(rf"^## {re.escape(version)}(?=[ \t\n])[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else None


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("tag")
    p.add_argument("--notes", help="write the changelog section for this version to this file")
    p.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    root = Path(args.root)

    version = package_version(root)
    if args.tag != f"v{version}":
        print(f"error: tag {args.tag} does not match package version v{version}", file=sys.stderr)
        return 1
    notes = changelog_section(version, root)
    if not notes:
        print(f"error: CHANGELOG.md has no '## {version}' section (or it is empty)", file=sys.stderr)
        return 1
    if args.notes:
        Path(args.notes).write_text(notes + "\n")
    print(f"ok: {args.tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
