# Code Style — Horus

Short, enforceable rules. Everything here is the team's working agreement.

## Comments and docstrings

### Rule 1 — one concept per file

The filename should predict the contents. If you cannot summarise a file in five
words without using "and", split it. Generic names (`utils.py`, `helpers.py`,
`core.py`) are banned unless the file is truly a one-concept "core" module
(e.g. `logger.py`, `config.py`).

### Rule 2 — docstrings are for API reference, not tutorials

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

### Rule 3 — docstring length cap

- Module docstring: ≤ 5 lines.
- Function / class docstring: ≤ 20 lines.
- Anything longer belongs in `docs/architecture/` or an ADR under `docs/architecture/adr/`.

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

| Content type | Location |
|--------------|----------|
| "Why we chose X over Y" | `docs/architecture/adr/NNNN-<topic>.md` (ADR) |
| How a subsystem works end-to-end | `docs/architecture/<service>.md` |
| Protocols (WebSocket, AMQP, HTTP contracts) | `docs/architecture/<service>.md` |
| Config / env vars | `docs/architecture/<service>.md` or `docs/configuration.md` |
| How to run locally | `docs/getting-started/` |
| Troubleshooting | `docs/troubleshooting.md` |

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

Unclaimed TODOs are auto-flagged in review.

## File organisation

- Route modules (`routes.py`) that exceed ~400 lines must be split into an
  `endpoints/` subpackage with one file per concern (see `mas/tasks/` as the
  reference shape).
- Tool-function modules (`*_tool_functions.py`) should follow the same rule.
- Cohesive schemas (SQLAlchemy models, Pydantic v2) may stay in one file even
  beyond 400 lines — they are a single concept.

## Tests

- Test filenames mirror the code filename: `routes/create.py` → `test_create.py`.
- Prefer a `tests/<service>/contract/` folder for behavior tests (things that
  should never change unless the feature changes) and `tests/<service>/unit/`
  for fast isolated tests.
- Files ending in `_coverage.py` are banned for new code. If you need to cover
  a line, add a real behavior test, not a coverage-theater test.

## Enforcement

- `ruff` runs on every push. The pydocstyle convention is already `google`.
- A pre-commit hook (to be added) will fail any Python file with a triple-quoted
  block longer than 40 lines. Overrides must be explicit (`# pragma: long-doc-ok`)
  and justified in review.
