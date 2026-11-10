# Releasing

Releases are cut by pushing a tag. `.github/workflows/release.yml` does the rest.

1. Branch `release/vX.Y.Z` from `main`.
2. Set `__version__` in `memdiag/__init__.py` (the only place; `pyproject.toml` reads it).
3. Rename `## Unreleased` in `CHANGELOG.md` to `## X.Y.Z`; these lines become the release notes.
4. Run locally: `ruff check . && pytest -q`, then `python -m build` and install the wheel in a fresh
   venv outside the repo and run `memdiag demo`.
5. Open a PR, get CI green and approval, merge to `main`.
6. Tag the merge commit and push the tag: `git tag vX.Y.Z && git push origin vX.Y.Z`.

The workflow then verifies the tag against the version and changelog, runs the test matrix,
builds and smoke-tests the wheel, and creates a GitHub Release (marked pre-release for
`aN`, `bN`, `rcN` versions). Publishing to PyPI is off until the repository variable
`PUBLISH_TO_PYPI` is `true` and a PyPI trusted publisher is configured.

A bad release is fixed forward with a new version. Do not move or delete a published tag.
