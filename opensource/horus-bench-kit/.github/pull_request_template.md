Fixes #

## What and why

## How I tested it

## Checklist

- [ ] The description says `Fixes #N`, with the issue's number.
- [ ] Every commit title follows the commit norm in CONTRIBUTING.md, and every commit is signed off (`git commit -s`).
- [ ] `pytest` passes, and the change comes with tests on synthetic data.
- [ ] `python scripts/make-zip.py` builds without a problem.
- [ ] A changed report format updates `docs/FORMATS.md`, and its `schema_version` when a key is removed, renamed or changes meaning.
- [ ] A user-visible change has a line under `Unreleased` in `CHANGELOG.md`.
