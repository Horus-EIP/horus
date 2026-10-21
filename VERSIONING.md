# Horus versioning and release policy

**When do we go from 0.1.2 to 0.1.3, 0.2.0 or 1.0.0, and how do we release?**

**Status:** proposal, not yet reviewed by the team. Written on 24/09/2026 for Tek5 Objective 1 ("use semver.org to define what will launch a new version and plan for the future"), checked against the code on 07/10/2026.

---

## 1. The scheme: Semantic Versioning 2.0.0

Every Horus release has a number **MAJOR.MINOR.PATCH** (see <https://semver.org>) and a git tag `vMAJOR.MINOR.PATCH`. Tags go on the working branch, `main` in `Horus-EIP/horus`.

| Part | Goes up when… | Example |
|---|---|---|
| **PATCH** (0.1.0 → 0.1.**1**) | We fix something, and nothing that customers or integrations rely on changes | Installer fix, bug fix, security patch |
| **MINOR** (0.1.x → 0.**2**.0) | We add a feature. **While we are below 1.0.0, also when we break something.** | Knowledge-store search UI, licence keys |
| **MAJOR** (0.x → **1**.0.0 → **2**.0.0) | 1.0.0 = first version we sell. After that, a breaking change (see section 4). | Public launch, Feb 2027 |

When a number goes up, the numbers to its right go back to 0: 0.1.3 → 0.2.0 and 0.9.2 → 1.0.0.

**One version for the whole product.** MAS, the agents, the knowledge store, the web client, the desktop app and the installer ship together, so they share **one** number, held in `VERSION`. We do not version the services separately. The evaluation set in `tests/eval/` is not part of the product and has its own version (see `tests/eval/README.md`).

---

## 2. Where the number lives

`VERSION` at the repository root holds the number and is the only place it is decided. It is `MAJOR.MINOR.PATCH`, optionally followed by a pre-release suffix such as `-rc.1` (section 6).

**Read from `VERSION`:**

| Consumer | How it gets the number |
|---|---|
| Installer (`installer/common.py`): its log and `--version` | Reads `VERSION`. The bundle ships `VERSION` at its root, next to `installer/`. |
| Bundle name `Horus-Beta-<version>.zip` (`packaging/build_bundle.py`) | Reads `VERSION` |
| Image names `<registry>/horus-<service>:<version>-<flavor>` | `HORUS_VERSION`, which the installer writes into `src/infra/.env`; `.github/workflows/images.yml` reads `VERSION` |
| MAS, agent and knowledge store: OpenAPI version and `GET /health`; the trace attribute `service.version` (MAS, agent); the `knowledge_store_system` info metric (knowledge store) | `HORUS_VERSION` from Compose. Outside Docker, the nearest `VERSION` file above the service, or `0.0.0` when there is none. |

**Copies that `scripts/ci/check-versions.py` compares with `VERSION`** (12 fields in 10 files):

| File | Field |
|---|---|
| `src/services/web-client/package.json` | `version`, which `GET /api/health` reports |
| `src/services/web-client/package-lock.json` | `version` and `packages[""].version` |
| `desktop/package.json` | `version` |
| `desktop/package-lock.json` | `version` and `packages[""].version` |
| `desktop/src-tauri/tauri.conf.json` | `version` |
| `desktop/src-tauri/Cargo.toml` | `package.version` |
| `desktop/src-tauri/Cargo.lock` | the `horus-desktop` entry |
| `desktop/ui/index.html` | the `Horus-Beta-<version>` placeholder |
| `src/infra/.env.example` | `HORUS_VERSION=`, for stacks started with `stack-up.sh` |
| `CHANGELOG.md` | the first heading that starts with a version number |

**To change the number:**

1. Write it in `VERSION`.
2. In `src/services/web-client` and in `desktop`, run `npm version` with the new number, for example `npm version 0.2.0 --no-git-tag-version`. It updates `package.json` and both fields of `package-lock.json`. Keep `--no-git-tag-version`: it stops npm from making its own commit and `v*` tag.
3. Edit the other copies by hand. The `horus-desktop` entry of `Cargo.lock` must match `Cargo.toml`, because the desktop builds run with `--locked`.
4. Give the `CHANGELOG.md` section the new number (section 7, step 3).
5. Run the check:

```bash
python scripts/ci/check-versions.py
```

It prints `All 12 version numbers match VERSION.`, or names each file, field and value that differs and exits with 1.

An existing `src/infra/.env` keeps the number it was created with: the installer rewrites `HORUS_VERSION`, but `stack-up.sh` only creates `.env` from `.env.example` when it is missing.

**Where the check runs:**

- The CI job `versions` in `.github/workflows/ci.yml`, on every pull request, on every push to `main` and to the Epitech repository's `master`, and by hand. It runs the tests in `tests/ci/` first (the check's own tests are in `tests/ci/test_check_versions.py`, and one of them checks the repository itself), then the check.
- `.github/workflows/desktop-release.yml` and `.github/workflows/images.yml`, on every `v*` tag. They also run `python scripts/ci/check-versions.py --tag "$GITHUB_REF_NAME"`, which fails when the tag is not `v` followed by `VERSION`. Then nothing is built or published.

---

## 3. What our version number protects (our public API)

SemVer only makes sense once we say what counts as a break. For Horus, these things matter to a customer or to an integration:

1. **The HTTP and WebSocket API of MAS**, used by the web client and by registered agents (`docs/api-reference.md`).
2. **The agent contract:** registration, API keys, RabbitMQ message format, heartbeats, skills.
3. **The install and upgrade path:**
   - keys in `src/infra/.env`
   - service names and ports in Docker Compose
   - image names and tags (`<registry>/horus-<service>:<version>-<flavor>`)
   - data volumes
   - database schema (Alembic migrations)
   - ChromaDB collections and the embedding model
4. **The licence-key format**, once licence keys exist (ADR-004).
5. **What the desktop app relies on:** the installer's `--start`, `--restart`, `--stop` and `--json-events`, and the web client at `https://localhost:3000`.
6. **Documented behaviour:** roles and permissions (admin / manager / user, see "Who can see what" in `docs/security.md`), the password policy, what each page does.

Anything else (internal modules, refactors, test code, internal prompts that don't change behaviour) can change in any release.

---

## 4. The rules

### While we are in 0.y.z (now → public launch)

SemVer says anything may change before 1.0.0. We are stricter, so that pilots and testers can trust the number.

**→ PATCH (0.1.0 → 0.1.1 → 0.1.2)** when **all** of these are true:

- only bug fixes, installer or packaging fixes, documentation fixes, security fixes, or dependency updates that don't change behaviour
- **no new feature**
- **no manual step** for the person upgrading (no new `.env` key to fill, no data migration they must run, no re-index)
- the existing API and agent contract keep working exactly as before

**→ MINOR (0.1.x → 0.2.0 → 0.3.0)** when **at least one** of these is true:

- a new user-facing feature, a new page, a new endpoint, or a new agent capability
- **anything breaking** (allowed before 1.0, but it must be written down):
  - an API endpoint changed or removed
  - a new required `.env` key
  - a database migration
  - a service added, removed or replaced in Compose
  - a change of embedding model that requires re-indexing
  - a change to the licence-key format
- the upgrade needs any manual step (described in `CHANGELOG.md` under **"Upgrading an existing install"**)

A commit titled with `[!]` (breaking) needs at least a MINOR release before 1.0.0, and a MAJOR one after.

**→ 1.0.0** when **all** of these are true:

- we sell it: first paid customer or public launch (planned: Epitech Experience, Feb 2027)
- the critical path passes on a clean CPU machine and on the GPU VM (see [TESTING.md](TESTING.md))
- licence keys and a THIRD_PARTY_NOTICES file are in place (ADR-004)
- the public API above is documented, and we commit to keeping it stable

### From 1.0.0 on (once customers depend on it)

| Change | Bump |
|---|---|
| Bug fix, security fix, no manual step, nothing removed | **PATCH** (1.0.0 → 1.0.1) |
| New feature or endpoint, backwards compatible; old clients and agents still work | **MINOR** (1.0.x → 1.1.0) |
| Something removed or incompatible: an API change that breaks the old web client or agents, a migration that can't run automatically, a forced re-index, an incompatible licence-key format, a dropped platform | **MAJOR** (1.x → 2.0.0) |

Before removing something in a MAJOR release, **deprecate it for at least one MINOR release**: it still works, but logs a warning and appears in the release notes.

---

## 5. Examples with real Horus changes

| Change | Before 1.0 | After 1.0 | Why |
|---|---|---|---|
| Fix the `/tasks/new` crash with duplicate filenames (ATP F25) | PATCH | PATCH | Bug fix, nothing changes for users |
| Give the first-install time as 1.5 to 2 hours in README-FIRST | PATCH | PATCH | Docs shipped in the ZIP |
| Remove PyMuPDF (unused) | PATCH | PATCH | No behaviour change |
| Task stats count root tasks only (ATP F28) | PATCH | PATCH | Bug fix |
| Back after logout no longer restores the session (ATP F7) | PATCH | PATCH | Security fix |
| Add a search field and a category filter to the knowledge store (ATP F13/F14) | MINOR | MINOR | New feature |
| Replace Redis with Valkey | MINOR | MINOR (or MAJOR if data must be migrated by hand) | Service replaced in Compose |
| Ship prebuilt images instead of building from source (B-66) | MINOR | MINOR | Install path changes |
| Introduce licence keys | MINOR | MAJOR if existing installs stop without a key | New required input to run |
| Change the embedding model (Unreleased: FastEmbed, and the knowledge store re-embeds every document once on its first start) | MINOR | MINOR when the re-index is automatic, as here; MAJOR when it is not | Existing data affected |
| A `user` who read other users' tasks now gets `403` (B-110) | MINOR | MAJOR | Documented permissions change for existing clients |
| Remove or rename an API endpoint | MINOR | MAJOR | Breaks clients and agents |
| New specialised agent, or the agent marketplace | MINOR | MINOR | New feature |
| Performance improvement, same behaviour | PATCH | PATCH | Nothing to adapt |

---

## 6. Where we are and the proposed roadmap

**Tagged:**

- **v0.1.0** (02/09/2026, `18704c0`): the first tagged beta.
- **v0.1.1** (07/09/2026, `0fc5378`): installer fixes (free disk raised to 150 GB, 125 GB with a GPU; one retry of `docker compose up`; offer to reclaim the Docker build cache; `--skip-disk-check`). Its installer still reported 0.1.0, because the bump commit only changed a document. This is why `VERSION` and the check exist.

Both tags point at commits of the `archive/Year_2025-2026` branch, which is in the Epitech repository; neither is on `main` or on the Epitech `master`.

**Not tagged yet:**

- **0.1.2**: `VERSION` says 0.1.2, and `CHANGELOG.md` has a `0.1.2 (unreleased)` section with the fixes for what the ATP testers hit (ATP v7, 18/09/2026). The tag waits for the smoke test on a clean CPU VM and on the GPU VM (B-47).
  0.1.2 is not a strict PATCH: it also adds the knowledge-store search and category filter (F13/F14) and two health endpoints, which section 4 calls MINOR. It was numbered before these rules were agreed; they apply from the next release.
- **Unreleased**: everything under `## Unreleased` in `CHANGELOG.md`. It needs upgrade steps (database migrations, a one-time re-embedding in the knowledge store, Docker Compose 2.33.0 or later) and changes who can read which task (B-110), so it ships as **0.2.0**, not 0.1.3.

**Proposed next versions** (dates follow the pitch timeline; adjust them together):

| Version | Content | Target |
|---|---|---|
| **0.1.2** (PATCH) | ATP fixes F25, F28, F7, F20, F15; image pulls one at a time with retries; one `VERSION` file; healthchecks; knowledge-store search and category filter (F13/F14); the 100-question evaluation set | Mid-October 2026 |
| **0.2.0** (MINOR) | Everything under Unreleased today: CPU profiles on one llama-server (B-87 to B-102), prebuilt signed images (B-66), tasks read and cancelled per owner (B-110), ATP fixes F29, F36 and F37. Still to do: Valkey, THIRD_PARTY_NOTICES. Used for the reproducibility test with an outsider | End of October 2026 |
| **0.3.0** (MINOR) | **Licence keys** + evaluation licence (ADR-004); first pilot companies | December 2026 |
| **0.4.0 → 0.x** (MINOR) | Autonomous agent and agent marketplace foundations (pitch roadmap Q4 2026 → Q1 2027) | Jan 2027 |
| **1.0.0** (MAJOR) | Public launch, first paid licences | Feb 2027 (Epitech Experience) |

**Pre-releases** for testers come before a MINOR or MAJOR: `0.2.0-beta.1`, then `0.2.0-rc.1`. Rules:

- A beta can still change.
- A release candidate (rc) only gets fixes.
- A pre-release is released like any other version: `VERSION`, every copy and the `CHANGELOG.md` heading say `0.2.0-rc.1`, and the tag is `v0.2.0-rc.1`. Its images are tagged `0.2.0-rc.1-cpu` and `0.2.0-rc.1-gpu`.
- The final `0.2.0` is the last rc with only the number changed: one commit sets `VERSION` and every copy to `0.2.0`, and that commit is tagged `v0.2.0`. The rc commit cannot simply be tagged again: the release workflows refuse a tag that differs from `VERSION`.

The ATP always names the exact version under test.

---

## 7. How we release (checklist)

1. **Decide the bump.** The PR author proposes it with a label (`semver:patch`, `semver:minor` or `semver:major`); the reviewer confirms it using section 4.
2. **Write `CHANGELOG.md`.** Use the sections already in use: Added, Changed, Fixed, plus **"Upgrading an existing install"** when the upgrade needs a manual step or a one-time action. Each entry cites its commit id. Check `packaging/RELEASE-NOTES.md` too: it becomes the text of the GitHub release.
3. **Bump the number** in one commit (section 2). In the same commit, rename `## Unreleased` to a numbered heading such as `## 0.2.0 (unreleased)`: the check skips `## Unreleased` and reads the first heading with a number. Work merged after this commit goes under a new `## Unreleased` above it.
4. **CI is green** on that commit (lint, version check, tests with coverage gates).
5. **Run the release tests:**
   - install on a clean CPU machine and on the GPU VM; the installer ends with its smoke test (`installer/smoke.py`), which must pass
   - for a MINOR release, the ATP subset on the changed features ([TESTING.md](TESTING.md))

   The installer pulls the images tagged with `VERSION`, and `images.yml` pushes those only for the tag `v<VERSION>`. To test the prebuilt images before the release, tag a release candidate (section 6). `--build-from-source` tests the same code without them.
6. **Tag the release commit and push the tag:**

   ```bash
   git tag -a v0.2.0 -m "Horus 0.2.0"
   git push origin v0.2.0
   ```

   A pushed `v*` tag starts two workflows:
   - `images.yml` builds the MAS, agent, knowledge-store and web-client images in their `cpu` and `gpu` flavors, pushes them as `<registry>/horus-<service>:<version>-<flavor>` and signs them (see "Prebuilt images" in `docs/operations.md`).
   - `desktop-release.yml` builds the desktop app (Windows `Horus.exe`, macOS `Horus.app`, Linux `.deb`) and `Horus-Beta-0.2.0.zip`, and drafts a GitHub release "Horus Beta 0.2.0" with `packaging/RELEASE-NOTES.md` as its text.

   Never push a `v*` tag to try something: it publishes.
7. **Publish the draft release**, then timestamp the archive with OpenTimestamps (`ots stamp Horus-Beta-0.2.0.zip`, proof of authorship and date, ADR-004). Keep the `.ots` file next to the MVP proof, in `docs/ip_protection/deposit_proof/` in the team's private repository.
8. **Date the `CHANGELOG.md` heading** and name the tag and its commit, as for 0.1.1: `## 0.1.1 - 2026-09-07`, then ``Tag `v0.1.1` (`0fc5378`).``
9. **Hotfix** (urgent PATCH on a released version): branch from the tag, fix with a test, bump to `X.Y.(Z+1)` with its `CHANGELOG.md` section, and open a PR so CI runs. Tag the hotfix commit itself: the working branch has moved on, and its `VERSION` names another release. Then merge the fix into the working branch, keeping that branch's own version number.

**Who tags:** the project lead (Loup), or another member when Loup is unavailable. Tags are never moved or deleted once pushed.
