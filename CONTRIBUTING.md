# Contributing to horus-bench-kit

Thanks for your interest in the kit. Its home is [github.com/Horus-EIP/horus-bench-kit](https://github.com/Horus-EIP/horus-bench-kit): issues, discussions and pull requests all happen there. Everyone who takes part follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## 1. Find an issue

- Issues labelled **`good first issue`** are small and say which files to look at. Issues labelled **`help wanted`** are open to anyone too.
- To take one, comment on it: "I'd like to work on this", or `/assign`. A bot assigns it to you and replies with the steps below. In French, "je voudrais travailler sur" or "je peux m'en occuper" works too.
- The rules:
  - open a draft pull request within **7 days**;
  - hold at most **two** claimed issues at a time;
  - comment `/unassign` to give an issue back;
  - without activity from you, meaning no comment from you on the issue and no open pull request of yours that mentions it (`Fixes #N`), the bot reminds you after **7 days** and unassigns the issue after **14 days**, so that someone else can take it.
- If the issue is already taken, the bot points you to other free ones.
- Questions go to [Discussions](https://github.com/Horus-EIP/horus-bench-kit/discussions). Bugs and feature requests go to issues, through the forms.

## 2. Make the change

1. Fork the repository, then create a branch named `<issue number>-<short-name>`, for example `12-csv-report`.
2. Install the kit with its test tools, then run the tests:

   ```sh
   python -m venv .venv
   . .venv/bin/activate            # Windows: .venv\Scripts\activate
   pip install -e ".[test]"
   pytest
   python scripts/make-zip.py      # refuses to build when a publishing check fails
   ```

3. Keep the kit's rules:
   - no runtime dependency outside the standard library (PyYAML stays optional);
   - Python 3.10 compatible;
   - `# SPDX-License-Identifier: Apache-2.0` as the first line of every Python file, and right after the shebang of a shell script;
   - a change to a report format updates [docs/FORMATS.md](docs/FORMATS.md), and a change that removes, renames or changes the meaning of a key raises that format's `schema_version`;
   - tests for every change, on synthetic data;
   - a user-visible change gets a line under `Unreleased` in [CHANGELOG.md](CHANGELOG.md).

## 3. Commits

Every commit title starts with one symbol and is written in the present tense:

| Symbol | Meaning | Use when… |
|---|---|---|
| `[+]` | Add | adding a file, a feature or a test |
| `[~]` | Update | changing or refactoring existing code |
| `[x]` | Fix | fixing a bug |
| `[-]` | Remove | deleting code or files |
| `[#]` | Docs | changing documentation or comments |
| `[?]` | Work in progress | committing unfinished work on your own branch |

Example:

```
[x] Compare: name the missing side when only one report is given

The table showed an empty column. It now says which report is missing.

Signed-off-by: Ada Lovelace <ada@example.org>
```

### Sign off every commit

Every commit carries a `Signed-off-by` line with the name and email of its author. By adding it you certify the [Developer Certificate of Origin](https://developercertificate.org/): you wrote the change, or have the right to send it under the project's licence. `git commit -s` adds the line from your Git `user.name` and `user.email`, so those must be the author's.

A check on every pull request fails when a commit has no matching line. To fix it:

```sh
git commit --amend --signoff --no-edit     # only the last commit
git rebase --signoff main                  # every commit of your branch, main being the branch you started from
git push --force-with-lease
```

## 4. Open the pull request

1. Open it against `main`, and write `Fixes #N` in the description so that the issue closes when it is merged. The template lists what to check.
2. CI runs the tests on Python 3.10 and 3.13, builds the zip and checks the sign-offs. On a first pull request, CI may wait until a maintainer approves the run.
3. A maintainer reviews it. Answer the comments, push fixes to the same branch, and resolve the conversations once they are settled.
4. With CI green and one maintainer's approval, the maintainer merges it with a merge commit.

## 5. Licence

The kit is licensed under the [Apache License 2.0](LICENSE). By its section 5, what you contribute is licensed under the same terms, with no extra agreement to sign: inbound equals outbound. The sign-off records that you may send it.

## 6. Security

Don't report a vulnerability in an issue: see [SECURITY.md](SECURITY.md).
