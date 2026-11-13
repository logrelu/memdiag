# Releasing

Releases are cut by pushing a tag. `.github/workflows/release.yml` does the rest.

## Release plan

| Release | Contents | Gate |
|---------|----------|------|
| v0.2.0rc1 | Release 1 candidate; the first real tag-push run, as a pre-release | Steps below |
| v0.2.0 | Release 1: validated turn-localized findings (see "Release 1" in `docs/ROADMAP.md`) | Release 1 criteria met and recorded in `docs/validation.md`; `docs/STABILITY.md` frozen |

There is no v0.1.0 tag: public names freeze at the first release, and they are still changing. Bump
`__version__` to `0.2.0rc1` on the release branch.

Before tagging a release that has success criteria, check each criterion and write the result in
the PR description. A missed criterion goes in the release notes with the number, not omitted.

## Steps

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

## Dry run

To check the pipeline without releasing anything, run the workflow manually from `main`:
`gh workflow run release` (or Actions tab, Run workflow). It runs verify, test and build, and skips
the GitHub Release and PyPI jobs. A failed verify step is only a warning in a dry run, so it works
while `CHANGELOG.md` still says "Unreleased". Check the run after any change to `release.yml`.
GitHub only offers manual runs for workflow files that exist on the default branch.

A bad release is fixed forward with a new version. Do not move or delete a published tag.
