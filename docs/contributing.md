# Contributing

How to work on Horus: workflow, code style, commit conventions, testing policy, and how issues are tracked. Includes the docs audit prompt for keeping documentation honest as code changes.

---

## Contributing to Horus AI

Thank you for your interest in contributing. This document explains the conventions and processes you need to follow.

### Getting Started

1. Read the [Developer Onboarding Guide](../getting-started/onboarding.md) to set up your environment.
2. Check the [open issues](https://github.com/EpitechPromo2027/G-EIP-600-BAR-6-1-eip-loup.marquez/issues) for available tasks.
3. All work begins as a GitHub Issue. Do not start coding without a linked issue.

### Branch Naming

Create a branch from `develop` (or the current integration branch) using the format:

```
issue-<id>-<short-description>
```

Examples:
- `issue-42-agent-heartbeat`
- `issue-99-fix-jwt-expiry`

### Commit Convention

Every commit message must follow this format:

```
[SYMBOL] Short title in present tense

Optional longer description explaining why the change was made.
```

| Symbol | Meaning | Use when... |
|--------|---------|-------------|
| `[+]` | Add | Adding a new file, feature, or functionality |
| `[~]` | Update / Refactor | Modifying or refactoring existing code |
| `[x]` | Fix | Fixing a bug, typo, or issue |
| `[-]` | Remove | Deleting code, files, or deprecated features |
| `[!]` | Breaking | Introducing breaking changes or hotfixes |
| `[#]` | Docs | Updating documentation or comments |
| `[>]` | Performance | Improving speed, memory, or efficiency |
| `[?]` | WIP | Committing unfinished or experimental code |

Example:
```
[+] Add agent heartbeat monitoring

Implemented background task that pings MAS every 30 seconds
to report agent health. Uses exponential backoff on failure.
```

### Pull Requests

1. Push your branch and open a Pull Request against `develop`.
2. Link the PR to the originating GitHub Issue.
3. **Two non-author approvals** are required before merge.
4. Use **Squash and Merge** when merging.
5. Delete the branch after merge.

### Code Style

This project follows the **Google Style Guides** for both languages:

#### Python

- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
- Enforced via [Ruff](https://docs.astral.sh/ruff/) (config in `pyproject.toml`)
- Google-style docstrings with `Args`, `Returns`, `Raises` sections
- 80-character line length
- Imports sorted: stdlib, third-party, local (with blank lines between groups)
- Type annotations on all public function signatures

#### TypeScript

- [Google TypeScript Style Guide](https://google.github.io/styleguide/tsguide.html)
- Enforced via ESLint + Prettier (configs in `src/services/web-client/`)
- Semicolons required, double quotes
- 80-character print width
- Imports sorted: external packages, internal `@/` aliases, relative
- TSDoc comments on all exported symbols

### Testing Requirements

Before submitting a PR, ensure:

1. **All existing tests pass.** Run:
   ```bash
   # Python services (from repository root; separate PYTHONPATH per service)
   pytest -c tests/mas/pytest.ini tests/mas -vv
   pytest -c tests/agent/pytest.ini tests/agent -vv
   pytest -c tests/knowledge_store/pytest.ini tests/knowledge_store -vv
   # Or: ./scripts/test/run-all.sh

   # Web client
   cd src/services/web-client && npm test
   ```

2. **New features include tests.** Follow the patterns in the existing test suites.

3. **No linter errors.** Run:
   ```bash
   # Python (from repo root)
   ruff check src/services/

   # TypeScript
   cd src/services/web-client && npm run lint
   ```

### Reporting Bugs

Open a GitHub Issue with:
- Steps to reproduce
- Expected behavior vs. actual behavior
- Environment details (OS, Docker version, browser)
- Relevant logs or screenshots

### Requesting Features

Open a GitHub Issue with the `enhancement` label describing:
- The problem the feature would solve
- Your proposed approach (if any)
- Any relevant context or mockups

---

## Contribution workflow

This repository uses a structured workflow to keep changes traceable and reviewable.

### Workflow summary

| Rule | Description |
|------|-------------|
| Task to issue | Work is tracked from a GitHub Issue when your team uses issues |
| Branch per issue | Branch names often follow `issue-<id>-<short-description>` |
| Commits | Follow [commit convention](commit-convention.md) |
| Pull requests | Link to the issue and request review per team policy |
| Merge | Use squash merge if that is team standard; delete the branch after merge |

Adjust approval counts and branch naming to match your organization’s rules.

---

### Task and issue tracking

All work must be associated with a GitHub **Issue**. No issue = no code.

#### Task rules

1. **Create a GitHub Issue** before you start any task.
2. **Create a Branch from that Issue** using:
   ```
   issue-<issue-number>-<short-description>
   ```

   _Example: `issue-42-agent-routing`_
3. **Assign yourself** to the issue.
4. **Estimate time** required (e.g., `2h`, `1d`, `3d`).
5. **Work only in that branch**, and reference the issue in your commits and PRs.
6. **Open a Pull Request**, link the issue with:
   ```
   Fixes #<issue-number>
   ```
7. **Get 2 reviewers from the group who DID NOT write the code**.
8. **Only merge after 2 approvals.**
9. **Use Squash & Merge**, then delete the branch.
10. **Issue closes automatically** if `Fixes #` is used, else close it manually.

#### Example issue template

```
Title: [Core] Implement communication handler

Description:
Create a core handler that routes messages between AI agents using internal protocol.

Estimate: 1d  
Assignee: @yourusername  
Labels: enhancement, AI  
Milestone: MVP v1  
```

---


## Git commit convention

To maintain a clean and understandable Git history, all commits in this repository must follow a standard format.

### Format

```
[SYMBOL] Short Title

Longer explanation of what was done, why it was done, and how (if necessary).
```

### Symbols and meanings

| Symbol | Meaning                   | Use when...                                               |
|--------|---------------------------|------------------------------------------------------------|
| [+]    | Add                       | Adding a new file, feature, class, or functionality        |
| [~]    | Update / Modify / Refactor| Updating or refactoring existing code                     |
| [x]    | Fix                       | Fixing a bug, typo, or issue                              |
| [-]    | Remove                    | Deleting code, files, or deprecated features              |
| [!]    | Important / Breaking      | Introducing breaking changes or hotfixes                  |
| [#]    | Docs / Comment            | Updating README, markdown, or inline comments             |
| [>]    | Performance / Optimization| Improving speed, memory, or efficiency                    |
| [?]    | Work In Progress (WIP)    | Committing unfinished or experimental code                |

### Description guidelines

- Use present tense in titles (e.g., "Add login module")
- Be short and clear in the title
- Provide context in the description when useful

### Example

```
[+] Add multi-agent orchestrator for Horus

Implemented a Python orchestrator module to manage inter-agent communication via RPC. Enables task delegation and supports modular agent plugins.
```

---

## Code Style — Horus

Short, enforceable rules. Everything here is the team's working agreement.

### Comments and docstrings

#### Rule 1 — one concept per file

The filename should predict the contents. If you cannot summarise a file in five
words without using "and", split it. Generic names (`utils.py`, `helpers.py`,
`core.py`) are banned unless the file is truly a one-concept "core" module
(e.g. `logger.py`, `config.py`).

#### Rule 2 — docstrings are for API reference, not tutorials

A docstring describes **what a function does, what it takes, what it returns,
what it raises**. Nothing else.

The ruff config enforces the **Google convention** (`tool.ruff.lint.pydocstyle`).
Stick to it.

```python
def add_messages(author: str, message: str, conversation_id: int, db: Session) -> Message:
    """Append a message to a conversation.

    Args:
        author: One of ``"user"``, ``"assistant"``, ``"system"``.
        message: Message body.
        conversation_id: Target conversation id.
        db: Active SQLAlchemy session.

    Returns:
        The newly created ``Message`` row.

    Raises:
        ConversationNotFound: If ``conversation_id`` does not exist.
    """
```

#### Rule 3 — docstring length cap

- Module docstring: ≤ 5 lines.
- Function / class docstring: ≤ 20 lines.
- Anything longer belongs in `docs/architecture.md` or an ADR under `docs/adr/`.

Exception: a Pydantic schema or SQLAlchemy model may have a slightly longer
docstring if it enumerates field meanings that are not obvious from types.

#### Rule 4 — inline comments explain WHY, not WHAT

```python
## BAD — narrates the code
## Loop over the items and add them to the list
for item in items:
    results.append(item)

## GOOD — explains why
## Preserve insertion order; client relies on it for UI ordering.
for item in items:
    results.append(item)
```

If you find yourself writing a WHAT comment, rename the variable or extract a
helper until the code explains itself.

#### Rule 5 — narrative goes to docs/

If you want to explain the **design** of a subsystem, a **protocol**, a
**decision**, or a **runbook**:

| Content type | Location |
|--------------|----------|
| "Why we chose X over Y" | `docs/adr/NNNN-<topic>.md` (ADR) |
| How a subsystem works end-to-end | `docs/architecture.md` (per-service section) |
| Protocols (WebSocket, AMQP, HTTP contracts) | `docs/architecture.md` + `docs/api-reference.md` |
| Config / env vars | `docs/operations.md` and `docs/getting-started.md` |
| How to run locally | `docs/getting-started.md` |
| Troubleshooting | `docs/getting-started.md` (Troubleshooting section) |

#### Rule 6 — section banners are OK, commented-out code is not

```python
## ────────────────── Constants ──────────────────
MAX_STEPS = 5

## ────────────────── Helpers ────────────────────
```

One-line banners for navigation are fine. Commented-out code is not — delete it
(`git log` remembers).

#### Rule 7 — no TODOs without owner

Every `# TODO` must include an author and an issue number:

```python
## TODO(loup, #142): replace with streaming response once client supports it
```

Unclaimed TODOs are auto-flagged in review.

### File organisation

- Route modules (`routes.py`) that exceed ~400 lines must be split into an
  `endpoints/` subpackage with one file per concern (see `mas/tasks/` as the
  reference shape).
- Tool-function modules (`*_tool_functions.py`) should follow the same rule.
- Cohesive schemas (SQLAlchemy models, Pydantic v2) may stay in one file even
  beyond 400 lines — they are a single concept.

### Tests

- Test filenames mirror the code filename: `routes/create.py` → `test_create.py`.
- Prefer a `tests/<service>/contract/` folder for behavior tests (things that
  should never change unless the feature changes) and `tests/<service>/unit/`
  for fast isolated tests.
- Files ending in `_coverage.py` are banned for new code. If you need to cover
  a line, add a real behavior test, not a coverage-theater test.

### Enforcement

- `ruff` runs on every push. The pydocstyle convention is already `google`.
- A pre-commit hook (to be added) will fail any Python file with a triple-quoted
  block longer than 40 lines. Overrides must be explicit (`# pragma: long-doc-ok`)
  and justified in review.

---

## Testing policy

### Scope

The Horus system is tested across Python services (MAS first), with CI running selected suites on every push and pull request.

### Types of tests

| Type | Status | Description |
|------|--------|-------------|
| Unit tests | Active | MAS core logic and APIs under `tests/mas/` (see CI for exclusions) |
| Integration tests | Active | `tests/mas/test_integration.py` against a running MAS instance (CI job `test-integration`) |
| End-to-end tests | Planned | Full stack including web client |
| Performance tests | Planned | Agent latency, RAG throughput |
| Security tests | Planned | Authorization, access control, data handling |

### Tools

- `pytest`, `pytest-asyncio`, `httpx`, `websockets` for Python  
- `coverage.py` where enabled locally (e.g. `scripts/test/run-mas.sh`)  
- GitHub Actions — `.github/workflows/ci.yml` at the repository root  

### Coverage goals

- Short term: maintain meaningful coverage on new MAS code paths touched by tests  
- Longer term: raise coverage on orchestration, auth, and task flows as suites grow  

### Example commands

```bash
## From repository root
pytest -c tests/mas/pytest.ini tests/mas -v

bash scripts/test/run-mas.sh
```

### Continuous testing

CI runs on each push and pull request; see the workflow file for Python version, infra services started with Docker Compose, and exact pytest invocations.

---

## Documentation Audit Prompt for Claude Code

Paste the section below into Claude Code, run from the repo root.

---

You are auditing the documentation of this repository (Horus AI — an EIP multi-agent orchestration platform). The goal is to find stale, contradictory, or missing documentation and propose concrete fixes. Treat code as the source of truth; treat docs as claims to verify against the code.

### Scope

Audit every `.md` file under:
- `/docs/**`
- Root-level: `README.md`, `beta_test_plan.md`
- `/greenlight/**/*.md`

Do NOT modify:
- `/docs/archive/**` (historical, frozen on purpose)
- `/docs/ip_protection/**` (legal documents, do not touch)
- Any `.pdf`, `.docx`, `.pptx` file
- Any file under `/src/`, `/tests/`, `/scripts/` unless verifying a doc claim

### What "stale" means here

For each doc, check it against the current code and config and flag:

1. **API drift** — endpoints, request/response schemas, WebSocket events, or auth flows in `docs/api-reference.md` that no longer match `src/`. Verify against actual route definitions, Pydantic models, and handlers.
2. **Architecture drift** — claims in `docs/architecture.md` (services, message buses, data stores, agent topology) that don't match the current `src/` layout or `docker-compose`/infra files. Verify ADRs in `docs/adr/` (`ADR-001-rabbitmq.md`, `ADR-002-chromadb.md`, `ADR-003-fastapi.md`) are still accurate — flag any "superseded" status that isn't documented.
3. **Config drift** — env vars, secrets, ports, service names mentioned in docs vs. `pyproject.toml`, `.env.example`, compose files, and `src/` config modules.
4. **Setup/onboarding drift** — `docs/getting-started.md` (Onboarding, Configuration, Troubleshooting sections): do the commands actually work? Are the prerequisites correct? Do referenced scripts in `/scripts/` still exist with the documented interface?
5. **Operations drift** — `docs/operations.md` (Deployment, Monitoring, Secrets, Environment Matrix sections): do they reference real environments and real metrics/dashboards?
6. **Broken internal links** — every relative link between markdown files (including the MkDocs `nav` in `docs/mkdocs.yml`).
7. **Dead references** — references to files, scripts, modules, or services that no longer exist.
8. **Contradictions** — two docs that say different things about the same component (e.g., one says Redis, another says ChromaDB).
9. **TODOs and placeholders** — any `TODO`, `TBD`, `FIXME`, `XXX`, `???`, "coming soon", "to be added", or empty section.
10. **Orphaned docs** — markdown files not referenced in `docs/mkdocs.yml` nav and not linked from any other doc.
11. **Orphaned root-level docs** — anything at the repo root that should be inside `/docs/` (currently the only intentional root-level doc is `beta_test_plan.md`). Propose where each should move and update the MkDocs nav.

### How to verify

For each claim, open the relevant code file and confirm. Do not trust docs against docs. Examples:
- `mas-api.md` says `POST /agents/spawn` → grep for the route in `src/`, check the handler signature, check the Pydantic schema.
- `rbac.md` lists roles → check the enum/constants in `src/`.
- `deployment.md` mentions a service → confirm it exists in compose/infra files.
- `environment-matrix.md` lists env vars → diff against `.env.example` and config loaders.

### Deliverables

Produce three things, in this order:

#### 1. `AUDIT_REPORT.md` at the repo root

For each doc file, one section:

```
#### path/to/doc.md
- Status: OK | NEEDS_UPDATE | BROKEN | ORPHANED | SHOULD_MOVE
- Last meaningful update: <date from git log>
- Issues found:
  - <issue> — evidence: <file:line in code>
  - <issue> — evidence: <file:line in code>
- Suggested action: <one of: update in place / move to <path> / merge into <doc> / delete / leave>
```

End the report with:
- A **summary table**: doc | status | severity (low/med/high).
- A **cross-cutting findings** section listing contradictions across multiple docs.
- A **prioritized fix list** (top 10 things to fix first).

#### 2. Concrete edits

After the report, apply the fixes that are unambiguous and low-risk:
- Fix broken internal links.
- Remove dead references.
- Update obviously stale config values (env vars, ports, service names) where the code clearly shows the current value.
- Move root-level docs into `/docs/` and update `mkdocs.yml` nav accordingly.
- Update `mkdocs.yml` to include any orphaned docs that should be in the nav, or list them under an "Archive" or "Reference" section.

For each edit, keep the diff small and focused. Do not rewrite prose for style. Only change what's factually wrong or structurally needed.

#### 3. `AUDIT_FOLLOWUPS.md`

Anything you found that needs a human decision (ambiguous semantics, ADRs that may need superseding, big rewrites, docs that may be obsolete entirely). One bullet per item, with a recommended action and the reasoning.

### Rules

- Be ruthless about evidence. Every "stale" claim must cite a code file and line.
- Never invent code that doesn't exist to justify a doc change. If you can't verify, mark as `NEEDS_HUMAN_REVIEW` and put it in `AUDIT_FOLLOWUPS.md`.
- Do not touch `/docs/archive/**` or `/docs/ip_protection/**`.
- Do not delete files without explicit listing in the followups doc first.
- Keep commit-sized diffs: if you're editing more than ~10 files in one pass, stop and report first.
- Run `mkdocs build --strict` at the end and fix any broken-link warnings it produces.

Start by listing all in-scope docs and giving me a 10-line plan of attack before doing any verification.
