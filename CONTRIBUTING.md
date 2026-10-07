# Contributing to Horus

Horus is a self-hosted platform where several AI agents answer questions from an organisation's own documents. It is built by three Epitech students as their final-year project (EIP), and it is **closed source**: see [LICENSE](LICENSE) and [ADR-004](docs/adr/ADR-004-closed-source-licence.md).

This page says how to take part: what to sign first, how work is tracked and how to send a change.

Contact: **contact@lothmar.com**

---

## 1. Before you start

1. **Sign the Contributor Agreement.** Nobody outside the team gets access to the code or the private documents before signing it. It covers confidentiality and, if you send work, the transfer of the rights in it; in return you get credit in [CONTRIBUTORS.md](CONTRIBUTORS.md), code review and a reference. Ask for it at contact@lothmar.com.
2. **Get access.** Once the agreement is signed by you and by the three maintainers, a maintainer gives you access to the repository. Turn on two-factor authentication on your GitHub account.
3. **Set up the project.** Follow [docs/getting-started.md](docs/getting-started.md). The short version is in the [README](README.md#quickstart).

Contributing is voluntary and unpaid. You choose what you work on and when, and you can stop at any time.

---

## 2. Finding something to work on

- All work is tracked in **GitHub issues**. Start from an issue, or open one before you write code.
- Issues labelled **`good first issue`** are small, self-contained and have the files to look at in their description.
- Say in the issue that you are taking it, so that two people don't do the same work.
- Not sure where to start? Ask in the issue, or write to contact@lothmar.com.

---

## 3. Sending a change

### Branches

- The working branch is **`Sprint#1_September2026_Tek5`**: until later in the year it plays the role of `master`. Start from it and open your pull request against it.
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
2. Say what you changed, why, and how you tested it.
3. If an AI assistant wrote a large part of the change, say so (see section 5).
4. CI must be green. Run the tests locally first (section 4).
5. **One approval** from a maintainer who did not write the change is needed. Changes to authentication, permissions or the installer's security checks need **two**. So will the licence-key check, once it is written ([ADR-004](docs/adr/ADR-004-closed-source-licence.md)).
6. The reviewer who approves merges the pull request, with a **merge commit** (not squash): the changelog cites commit ids.
7. The branch is deleted after the merge.

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

---

## 5. Code from elsewhere and AI tools

- **No copied code without its licence.** If you copy code from another project, name the source and its licence in the pull request. Code under the GPL, AGPL or SSPL, or code with no licence, can't be used.
- **New dependencies** are named in the pull request with their licence.
- **Online services:** don't paste or upload Horus code or documents into online services (AI assistants, translators, pastebins, forums) unless the maintainers have approved that service by email. GitHub is approved for the Horus repositories. Tools that run entirely on your own computer are fine.
- **AI-written code:** you may use AI coding tools within the rule above, as long as you review and understand everything you submit, and say in the pull request when a large part was generated.

---

## 6. Reporting a problem

- **Bugs:** open an issue with the steps to reproduce, what you expected, what happened, your OS, Docker version and hardware profile, and the relevant logs. For the installer, attach `install-log.txt` and `horus-profile.json`: they are written next to the START-HERE files, or at the repository root when you run `installer/horus_install.py` from a clone.
- **Ideas:** open an issue labelled `enhancement` with the problem it solves.
- **Security issues:** don't open a public issue. Write to contact@lothmar.com with the details; we answer within a week.
