# Code Style — Horus

How to contribute (branches, commits, pull requests, tests, reporting problems) is in [CONTRIBUTING.md](../CONTRIBUTING.md); this page only holds the code style rules.

Short, enforceable rules. Everything here is the team's working agreement.

---

## Language guides

### Python

- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html).
- Google-style docstrings with `Args`, `Returns`, `Raises` sections.
- Lines up to 100 characters (`line-length = 100` in `pyproject.toml`).
- Imports sorted: standard library, third-party, local, with a blank line between groups.
- Type annotations on all public function signatures.

Ruff (config in `pyproject.toml`) checks bugs and import order only. It does not check docstrings, type annotations, naming or line length: the `D`, `ANN` and `N` rules are off and `E501` is ignored.

### TypeScript

- [Google TypeScript Style Guide](https://google.github.io/styleguide/tsguide.html).
- Semicolons, double quotes, 80-character lines: the Prettier settings in `src/services/web-client/.prettierrc`. No npm script runs Prettier, so run it from your editor.
- Imports sorted: external packages, internal `@/` aliases, relative.
- TSDoc comments on all exported symbols.

ESLint (`npm run lint`, config in `src/services/web-client/eslint.config.mjs`) applies the Next.js `core-web-vitals` and `typescript` rule sets.

---

## Comments and docstrings

### Rule 1 — one concept per file

The filename should predict the contents. If you cannot summarise a file in five
words without using "and", split it. Generic names (`utils.py`, `helpers.py`,
`core.py`) are banned unless the file is truly a one-concept "core" module
(e.g. `logger.py`, `config.py`).

### Rule 2 — docstrings are for API reference, not tutorials

A docstring describes **what a function does, what it takes, what it returns,
what it raises**. Nothing else.

Use the **Google convention**. Ruff does not check it, so reviewers do.

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

### Rule 3 — docstring length cap

- Module docstring: ≤ 5 lines.
- Function / class docstring: ≤ 20 lines.
- Anything longer belongs in `docs/architecture.md` or an ADR under `docs/adr/`.

Exception: a Pydantic schema or SQLAlchemy model may have a slightly longer
docstring if it enumerates field meanings that are not obvious from types.

### Rule 4 — inline comments explain WHY, not WHAT

```python
# BAD — narrates the code
# Loop over the items and add them to the list
for item in items:
    results.append(item)

# GOOD — explains why
# Preserve insertion order; client relies on it for UI ordering.
for item in items:
    results.append(item)
```

If you find yourself writing a WHAT comment, rename the variable or extract a
helper until the code explains itself.

### Rule 5 — narrative goes to docs/

If you want to explain the **design** of a subsystem, a **protocol**, a
**decision**, or a **runbook**:

| Content type                                | Location                                               |
| ------------------------------------------- | ------------------------------------------------------ |
| "Why we chose X over Y"                     | `docs/adr/ADR-NNN-<topic>.md` (ADR)                  |
| How a subsystem works end-to-end            | `docs/architecture.md` (per-service section)         |
| Protocols (WebSocket, AMQP, HTTP contracts) | `docs/architecture.md` + `docs/api-reference.md`   |
| Config / env vars                           | `docs/operations.md` and `docs/getting-started.md` |
| How to run locally                          | `docs/getting-started.md`                            |
| Troubleshooting                             | `docs/getting-started.md` (Troubleshooting section)  |

### Rule 6 — section banners are OK, commented-out code is not

```python
# ────────────────── Constants ──────────────────
MAX_STEPS = 5

# ────────────────── Helpers ────────────────────
```

One-line banners for navigation are fine. Commented-out code is not — delete it
(`git log` remembers).

### Rule 7 — no TODOs without owner

Every `# TODO` must include an author and an issue number:

```python
# TODO(loup, #142): replace with streaming response once client supports it
```

Reviewers flag any TODO without an owner and an issue.

---

## File organisation

- Route modules (`routes.py`) that exceed ~400 lines must be split into an
  `endpoints/` subpackage with one file per concern. None has been split yet:
  `src/services/mas/tasks/routes.py` is over the limit.
- Tool-function modules (`*_tool_functions.py`) should follow the same rule.
- Cohesive schemas (SQLAlchemy models, Pydantic v2) may stay in one file even
  beyond 400 lines — they are a single concept.

---

## Tests

- Test filenames mirror the code filename: `routes/create.py` → `test_create.py`.
- Fast isolated tests go in `tests/<service>/unit/`; tests that call a
  service's HTTP routes go in `tests/<service>/api/`.
- Files ending in `_coverage.py` are banned for new code. If you need to cover
  a line, add a real behavior test, not a coverage-theater test.

---

## Enforcement

- CI runs `ruff check src tests scripts installer packaging` (ruff 0.16.6, job
  `lint` in `.github/workflows/ci.yml`) on every pull request. It does not
  check docstrings.
- The pre-commit hook `docstring-length` (`.pre-commit-config.yaml`) fails any
  Python file with a triple-quoted block longer than 40 lines
  (`scripts/ci/check-docstring-length.py`). It skips tests, migrations and
  Alembic versions. It runs only once you have run `pre-commit install`; CI
  does not run it, and there is no override comment.
