# Contributing to Horus AI

Thank you for your interest in contributing. This document explains the conventions and processes you need to follow.

## Getting Started

1. Read the [Developer Onboarding Guide](../getting-started/onboarding.md) to set up your environment.
2. Check the [open issues](https://github.com/EpitechPromo2027/G-EIP-600-BAR-6-1-eip-loup.marquez/issues) for available tasks.
3. All work begins as a GitHub Issue. Do not start coding without a linked issue.

## Branch Naming

Create a branch from `develop` (or the current integration branch) using the format:

```
issue-<id>-<short-description>
```

Examples:
- `issue-42-agent-heartbeat`
- `issue-99-fix-jwt-expiry`

## Commit Convention

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

## Pull Requests

1. Push your branch and open a Pull Request against `develop`.
2. Link the PR to the originating GitHub Issue.
3. **Two non-author approvals** are required before merge.
4. Use **Squash and Merge** when merging.
5. Delete the branch after merge.

## Code Style

This project follows the **Google Style Guides** for both languages:

### Python

- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
- Enforced via [Ruff](https://docs.astral.sh/ruff/) (config in `pyproject.toml`)
- Google-style docstrings with `Args`, `Returns`, `Raises` sections
- 80-character line length
- Imports sorted: stdlib, third-party, local (with blank lines between groups)
- Type annotations on all public function signatures

### TypeScript

- [Google TypeScript Style Guide](https://google.github.io/styleguide/tsguide.html)
- Enforced via ESLint + Prettier (configs in `src/services/web-client/`)
- Semicolons required, double quotes
- 80-character print width
- Imports sorted: external packages, internal `@/` aliases, relative
- TSDoc comments on all exported symbols

## Testing Requirements

Before submitting a PR, ensure:

1. **All existing tests pass.** Run:
   ```bash
   # Python services (from repository root; separate PYTHONPATH per service)
   pytest -c tests/mas/pytest.ini tests/mas -vv
   pytest -c tests/agent/pytest.ini tests/agent -vv
   pytest -c tests/knowledge_store/pytest.ini tests/knowledge_store -vv
   # Or: ./scripts/ci/run_all_python_tests.sh

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

## Reporting Bugs

Open a GitHub Issue with:
- Steps to reproduce
- Expected behavior vs. actual behavior
- Environment details (OS, Docker version, browser)
- Relevant logs or screenshots

## Requesting Features

Open a GitHub Issue with the `enhancement` label describing:
- The problem the feature would solve
- Your proposed approach (if any)
- Any relevant context or mockups
