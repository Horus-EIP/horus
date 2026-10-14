# Contributing to Horus

Horus is a self-hosted platform where several AI agents answer questions from an organisation's own documents. It is built by three Epitech students as their final-year project (EIP), and it is **closed source**: see [LICENSE](LICENSE) and [ADR-004](docs/adr/ADR-004-closed-source-licence.md).

This page says how to take part: what to sign first, how work is tracked, how to send a change, and how the maintainers decide.

Contact, the three maintainers: **loup.marquez@epitech.eu**, **noah.gibelli@epitech.eu** and **matheus.lopez@epitech.eu**.

---

## 1. Before you start

1. **Sign the Contributor Agreement.** Nobody outside the team gets access to the code or the private documents before signing it. It covers confidentiality and, if you send work, the transfer of the rights in it; in return you get credit in [CONTRIBUTORS.md](CONTRIBUTORS.md), code review and a reference. Ask one of the maintainers for it (addresses under Contact above).
2. **Get access.** Once the agreement is signed by you and by the three maintainers, a maintainer adds you to the Horus-EIP organisation (see [Outside contributors](#outside-contributors)). Turn on two-factor authentication on your GitHub account: the organisation requires it.
3. **Set up the project.** Follow [docs/getting-started.md](docs/getting-started.md). The short version is in the [README](README.md#contributors-from-the-repository).

Contributing is voluntary and unpaid. You choose what you work on and when, and you can stop at any time.

---

## 2. Finding something to work on

- All work is tracked in **GitHub issues**. Start from an issue, or open one before you write code.
- Issues labelled **`good first issue`** are small, self-contained and have the files to look at in their description.
- Say in the issue that you are taking it, so that two people don't do the same work.
- Not sure where to start? Ask in the issue, or write to one of the maintainers.

---

## 3. Sending a change

### Outside contributors

If you are not one of the three maintainers:

1. Once your Contributor Agreement has all four signatures, yours and the three maintainers', a maintainer invites you to the [Horus-EIP](https://github.com/Horus-EIP) organisation as a member, in the team `signed-contributors`. That team has Read access to this repository, so you can read it and fork it, but not push to it.
2. Fork `Horus-EIP/horus`, create your branch in your fork (see [Branches](#branches)), follow the [commit norm](#commits), and open a pull request against `main` in `Horus-EIP/horus`.
3. CI on your pull request waits for a maintainer's approval, at every push: in a private repository, GitHub runs workflows from a fork only once someone with write access approves them (**Approve workflows to run**).
4. A maintainer reviews and merges, as described in [How we merge](#how-we-merge).

### Branches

- The working branch is **`main`** in [`Horus-EIP/horus`](https://github.com/Horus-EIP/horus). Start from it and open your pull request against it.
- The Epitech repository's `master` receives our work through a sync pull request from `main` after each batch of merged work. Nobody commits there directly.
- Name your branch `issue-<number>-<short-description>`, for example `issue-42-agent-heartbeat`.

### Commits

Every commit title starts with one symbol and is written in the present tense:

| Symbol | Meaning | Use when… |
|---|---|---|
| `[+]` | Add | adding a file, a feature or a test |
| `[~]` | Update | changing or refactoring existing code |
| `[x]` | Fix | fixing a bug |
| `[-]` | Remove | deleting code or files |
| `[!]` | Breaking | changing behaviour other parts rely on |
| `[#]` | Docs | changing documentation or comments |
| `[>]` | Performance | making something faster or lighter |
| `[?]` | Work in progress | committing unfinished work on your own branch |

Example:

```
[x] Knowledge store: return a generic message when a search fails

The exception text was sent to the client. It now goes to the log
with the request id, and the client gets a fixed message.
```

### Pull requests

1. Link the issue in the description: `Fixes #<number>`.
2. Say what you changed, why, and how you tested it. The pull request template lists what to check.
3. If an AI assistant wrote a large part of the change, say so (see section 5).
4. Run the tests locally first (section 4).

### How we merge

- **CI is green.**
- **One approval** from a maintainer who did not write the change. Changes to authentication, permissions or the installer's security checks need **two**. So will the licence-key check, once it is written ([ADR-004](docs/adr/ADR-004-closed-source-licence.md)).
- **A merge commit, never squash:** the changelog cites commit ids. The reviewer who approves merges the pull request. GitHub then deletes the branch if it is in `Horus-EIP/horus`; delete a branch in your fork yourself.

GitHub can't enforce these rules on a private repository on the Free plan: required reviews and required checks need a paid plan there. So we hold ourselves to them. `.github/CODEOWNERS` names the `maintainers` team as the owner of every file; GitHub acts on it in a private repository only on a paid plan, so until then it records who reviews.

### The benchmark kit

The benchmark and evaluation kit in `opensource/horus-bench-kit/` is open source, under the Apache License 2.0, and lives in its public repository, [`Horus-EIP/horus-bench-kit`](https://github.com/Horus-EIP/horus-bench-kit). Once that repository is published, change the kit only there, with a pull request that follows its own CONTRIBUTING.md: never in this repository.

Its changes come back here through a pull request in `Horus-EIP/horus` that pulls the public repository into the folder (the `git remote add` is needed once per clone):

```bash
git remote add kit https://github.com/Horus-EIP/horus-bench-kit.git
git switch -c kit-update main
git subtree pull --prefix=opensource/horus-bench-kit kit main -m "[~] Bench kit: changes from the public repo"
git push -u origin kit-update
```

The first time, run this before the `git subtree pull`:

```bash
git subtree split --prefix=opensource/horus-bench-kit --rejoin -m "[~] Bench kit: join the public repository's history"
```

The public repository was made with `git subtree split`, which leaves no trace in `main`, so a first `git subtree pull` stops with "refusing to merge unrelated histories". The `--rejoin` split rebuilds the same commits as the published ones and joins them to `main` with a merge commit. Once that pull request is merged, later pulls don't need it: `git log --oneline --grep="git-subtree-dir: opensource/horus-bench-kit" main` lists the join once it is there.

---

## 4. Tests and style

- How we test, and what each suite covers: [TESTING.md](TESTING.md).
- Run the Python suites from the repository root:

  ```bash
  pytest -c tests/mas/pytest.ini tests/mas -m "not requires_stack" -vv
  pytest -c tests/agent/pytest.ini tests/agent -vv
  pytest -c tests/knowledge_store/pytest.ini tests/knowledge_store -vv
  ```

- Check Python the way CI does (job `lint` in `.github/workflows/ci.yml`):

  ```bash
  pip install ruff==0.16.6
  ruff check src tests scripts installer packaging
  ```

- Web client (Node.js 20 or newer). CI does not run these checks, so run them yourself whenever you change the web client:

  ```bash
  cd src/services/web-client
  npm ci
  npm run lint && npm run typecheck && npm test
  ```

- New code comes with tests. A bug fix comes with a test that fails before the fix.
- Code style rules (docstrings, comments, file size): [docs/contributing.md](docs/contributing.md).
- How errors are reported and inputs validated: [docs/validation-and-error-handling.md](docs/validation-and-error-handling.md).
- Version numbers and releases: [VERSIONING.md](VERSIONING.md).

### Dependencies and lock files

The images install the Python packages from lock files, with exact versions and hashes: `requirements.lock` and `requirements-gpu.lock` next to each service's `requirements.txt` and `requirements-gpu.txt` (MAS also has `requirements-cpu.lock`). They are compiled for Python 3.11 on Linux x86-64, the Python of the images. The CI test jobs still install the `.txt` files. Test tools (pytest and its plugins, and packages only the tests import, such as fakeredis) go in the service's `requirements-test.txt`, which only CI and your own environment install: it has no lock and never reaches an image.

To add, remove or upgrade a Python dependency:

1. Edit the `requirements*.txt` file.
2. Run `scripts/dev/lock-requirements.sh`, which needs [uv](https://docs.astral.sh/uv/). It keeps every locked version it can; add `--upgrade-package NAME` to move one package, or `--upgrade` to move them all. It compiles the GPU lock first and the CPU lock against it, so both install the same versions.
3. Update the licence data, with `--python-env` once for each local environment that has the packages installed (the rest is read from PyPI). Then fetch the licence texts and NOTICE files into `LICENSES/` and `NOTICES/`, and rewrite `THIRD_PARTY_NOTICES`; this step needs the network:

   ```bash
   python scripts/licences/third_party_notices.py --refresh python --python-env PATH/TO/python
   python scripts/licences/third_party_notices.py --refresh files
   ```

4. Commit the `.txt` and `.lock` files, `scripts/licences/python-packages.json` and `licence-files.json`, `LICENSES/`, `NOTICES/` and `THIRD_PARTY_NOTICES` together. The CI job `licences` fails when they are out of date, when a licence in use has no text in `LICENSES/`, or when a NOTICE a component ships is missing from `NOTICES/`.

When you change a Dockerfile's base image or the system packages its final stage installs, the list of GPL and LGPL system packages in `THIRD_PARTY_NOTICES` has to follow: build the four CPU images and run `--refresh system` ([Prebuilt images](docs/operations.md#prebuilt-images) in `docs/operations.md`). The CI job `licences` fails until then.

---

## 5. Code from elsewhere and AI tools

- **No copied code without its licence.** If you copy code from another project, name the source and its licence in the pull request. Code under the GPL, AGPL or SSPL, or code with no licence, can't be used.
- **New dependencies** are named in the pull request with their licence. The CI job `licences` fails on a GPL, AGPL or SSPL licence among the Python packages, the web client's production dependencies and the desktop app's crates; an exception needs the maintainers' review and a line with its reason in `scripts/licences/allowlist.yaml`.
- **Online services:** don't paste or upload Horus code or documents into online services (AI assistants, translators, pastebins, forums) unless the maintainers have approved that service and listed it here ([How we decide](#7-how-we-decide)). GitHub is approved for the Horus repositories. Tools that run entirely on your own computer are fine.
- **AI-written code:** you may use AI coding tools within the rule above, as long as you review and understand everything you submit, and say in the pull request when a large part was generated.

---

## 6. Reporting a problem

- Issues are opened with a form: **Bug report** or **Task**. Blank issues are off. Issues about the benchmark and evaluation kit go to its own repository, [`Horus-EIP/horus-bench-kit`](https://github.com/Horus-EIP/horus-bench-kit).
- **Bugs:** open an issue with the Bug report form: the steps to reproduce, what you expected, what happened, your OS, Docker version and hardware profile, and the relevant logs. For the installer, attach `install-log.txt` and `horus-profile.json`: they are written next to the START-HERE files, or at the repository root when you run `installer/horus_install.py` from a clone.
- **Ideas:** open an issue with the Task form, starting from the problem it solves.
- **Security issues:** don't open a public issue. Write to the three maintainers (addresses under Contact above) with the details; we answer within a week.

---

## 7. How we decide

Horus belongs to its three maintainers together: Loup Marquez-Luttringer, Noah Gibelli and Matheus Lopez. This section says how the three of us take decisions beyond a single change; the review of a change follows [How we merge](#how-we-merge). Contributors don't vote, but they can propose something in an issue; a maintainer who takes it up opens the branch and the pull request.

### Two of three

Most decisions need two of the three maintainers to agree:

- technical choices: the architecture, dependencies, tools and CI;
- what goes into a release, and when it is tagged;
- the backlog and the sprints: priorities, who does what, and the dates.

### All three

These need all three maintainers to agree:

- the licence: any change to [LICENSE](LICENSE), and what is open source and what stays closed ([ADR-004](docs/adr/ADR-004-closed-source-licence.md), [ADR-007](docs/adr/ADR-007-open-source-benchmark-kit.md));
- anything that gives someone rights in Horus or the right to use it: a Contributor Agreement, an Evaluation Licence, a commercial licence, or a transfer of the rights to a company;
- adding a maintainer, or giving someone write access to a Horus-EIP repository;
- changing this section, How we decide.

An all-three decision waits for the third maintainer: the other two can't take it alone, even when he is away.

For an agreement, the signatures of all three are the decision: it needs no issue or pull request, and the signed copy stays in the team's private folder, never in a repository, because it holds the person's details.

### Every decision is a pull request

Apart from a signed agreement, a decision counts only once it is approved in a pull request on GitHub, so anyone can see what was decided, who agreed and why. Talking it over at a meeting or on another platform is fine, but nothing is decided there. A decision follows the same steps as any other work:

1. **An issue.** Whoever proposes the decision opens an issue that says what is to be decided and why: in `Horus-EIP/horus` for a decision about how Horus is built, licensed or run, in the team's private repository, `Horus-EIP/horus-team`, for a planning decision (priorities, who does what, dates).
2. **A branch** for that issue, named `issue-<number>-<short-description>` (see [Branches](#branches)), with:
   - for a decision about how Horus is built, licensed or run: a new **ADR** in [`docs/adr/`](docs/adr/), one ADR per decision, whose **Deciders** line names who agreed;
   - for a release: the change that sets `VERSION` and dates its section in `CHANGELOG.md` ([VERSIONING.md](VERSIONING.md));
   - for a rule written in a document, like the approved online services in section 5: the change to that document;
   - for a planning decision: the change to the sprint plan.
3. **A pull request** that says `Fixes #<number>` and requests a review from the two other maintainers. They answer there: **Approve** if they agree, **Request changes** if they don't, and comments for questions.
4. **The merge**, once enough of us approve: one approval for a two-of-three decision (the author is the second voice), the two others' approvals for an all-three decision. A two-of-three pull request stays open at least 48 hours, unless all three have reviewed it, so the third maintainer can see it and comment first.

A decision stays until a new one replaces or amends it, through the same steps: the new ADR says which one it supersedes or amends, and the old one's status says so ("Superseded by ADR-NNN" or "Amended by ADR-NNN").

Choices inside a single task, like how to write a function, are settled in that task's own pull request.

Until two of us agree, or all three for the decisions above, nothing changes.
