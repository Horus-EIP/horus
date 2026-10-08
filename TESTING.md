# Horus test strategy

How we test, where tests live, how we name them, and when a test is required.

**Status:** proposal, not yet reviewed by the team. Written on 24/09/2026 for Tek5 Objective 2 (action 10), checked against the code on 07/10/2026.

---

## 1. What must never break

### The critical path

If any step fails, Horus is of no use to the customer.

```
Install -> Log in -> Upload a document -> Search it -> Ask a question
  -> Grounded answer that names its source (or an honest "the documents do not say")
  -> Task routed to the agent with the right skill -> Result pushed over WebSocket
```

`installer/smoke.py` walks most of this path at the end of every install (see 2.10).

### Sensitive parts

These need their own, stricter tests.

| Area | Why it is sensitive | Minimum tests | Where today |
|---|---|---|---|
| **Auth**: login, JWT, refresh, logout | A flaw means a full takeover | Unit + API: wrong password -> 401, expired token -> 401, logout ends the session (ATP F7) | `tests/mas/api/test_auth.py`; F7 in `src/services/web-client/__tests__/navbar-logout.test.tsx` |
| **Access control and data isolation** | User A must never see user B's conversations, tasks or documents | API tests for each role (admin, manager, user) and a two-user test | `tests/mas/api/test_task_access.py`, `test_conversations.py`; role fixtures `as_admin`, `as_manager`, `as_user` in `tests/mas/api/conftest.py` |
| **Password policy** | Same rule at sign-up, in the admin panel and on the server | API test: weak password -> 422 with a readable message (ATP F5) | `check_password_policy` in `src/services/mas/schemas/schemas.py` |
| **Document deletion** | A deleted document must leave search *and* chat (ATP F15) | API test + a check on a live stack | `tests/knowledge_store/api/test_document_deletion_flow.py` |
| **Grounding and refusal** | The core promise: never invent an answer | The evaluation set (section 6) before each release | `tests/eval/testset.yaml`, `scripts/eval/run-eval.py` |
| **Installer preflight** | A wrong check wastes hours of a tester's time | Disk, ports, hardware and profile choice | `installer/tests/` (`test_preflight_requirements.py`, `test_hardware_decision.py`, `test_profile_tuning.py`) |
| **Licence key** | A bug blocks paying customers or gives Horus away | Unit tests for every state: valid, warning, grace, expired, tampered, clock rollback | Not built yet; design in `docs/adr/ADR-004-closed-source-licence.md` |

---

## 2. Which type of test covers which part

| # | Type | What it covers | Where it lives | Tool | When it runs |
|---|---|---|---|---|---|
| 2.1 | **Unit (Python)** | Pure logic: schemas, routing rules, tools, helpers; external systems mocked | `tests/<service>/unit/` | pytest, pytest-asyncio (`asyncio_mode = auto`), fakeredis (MAS), mocks in `conftest.py` | CI (`ci.yml`), with coverage gates |
| 2.2 | **API (Python)** | FastAPI endpoints through a test client: status codes, auth, validation, response shape | `tests/<service>/api/` | pytest, FastAPI `TestClient` / httpx | CI (`ci.yml`) |
| 2.3 | **Web client** | API clients, hooks, components with logic | `src/services/web-client/__tests__/` | Vitest, Testing Library, jsdom | Locally only. Not in CI |
| 2.4 | **Installer** | Preflight, hardware and profile choice, consent, model manager, smoke-test parsing, bundle | `installer/tests/` | `unittest` | `desktop-release.yml` and `images.yml`, on a `v*` tag or by hand. Not on pull requests |
| 2.5 | **CI wiring** | Version numbers, CPU build wiring, release images, repository wiring, third-party notices | `tests/ci/` | `unittest` | CI (`ci.yml` jobs `versions`, `licences` and `cpu-build-wiring`; `images.yml`) |
| 2.6 | **Evaluation set checks** | The 100-question set itself, the eval runner's scoring and reports, the benchmark tooling | `tests/eval/` | pytest, hermetic | `eval-testset.yml`, when `demo_assets/`, `tests/eval/`, `scripts/eval/`, `scripts/benchmarks/` or the two reused `scripts/perf/` scripts change |
| 2.7 | **Grounding evaluation** | Answers are correct, cite the right document, and out-of-corpus questions are refused | `tests/eval/testset.yaml` + `scripts/eval/run-eval.py` | Runner against a live stack; results in `benchmarks/` | By hand, before each release (section 6) |
| 2.8 | **Integration checks** | Two or more real services together (MAS, RabbitMQ, Postgres, agent, knowledge store) | `scripts/integration-checks/` (20 files) | pytest or python, against a live stack | By hand. Not in CI (section 7) |
| 2.9 | **MAS client scripts** | Manual calls to a running MAS on `localhost:8000` | `tests/mas/client_tests/` | python | By hand. pytest does not collect them (file names start with `client_`) |
| 2.10 | **End-to-end smoke** | Knowledge store health, unauthenticated call refused, admin login, token accepted, a worker agent registers, the demo document is ingested, a question about it, the answer is grounded, a negative control question | `installer/smoke.py` (9 steps) | Run by the installer, or `python installer/smoke.py` on a running stack | End of every install (unless `--skip-smoke`); every release candidate on a clean CPU machine and on a GPU machine |
| 2.11 | **Acceptance (manual)** | Real users following written scenarios | `docs/eip_pool_tek5/Horus_ATP_v7.xlsx` (37 scenarios, F1 to F37) | Testers and the results sheet | Before each beta or MINOR release |
| 2.12 | **Performance and load** | Latency, throughput, retrieval quality, llama.cpp speed | `scripts/perf/` (locust, benchmarks), `scripts/benchmarks/` | locust, Python scripts | Before a MINOR release, and after a performance change. See `scripts/perf/README.md` and `benchmarks/README.md` |
| 2.13 | **Static checks** | Lint, import order, likely bugs | Repo-wide | ruff 0.16.6 (CI), pre-commit (ruff `--fix`, `ruff-format`, docstring length), bandit (by hand) | ruff in CI; the last bandit report is `greenlight/code-quality-review/bandit_report.txt` (31/05/2026) |

**What counts as a regression test:** any test written *because a bug happened* (section 4). It can be of any type above.

---

## 3. Where tests live

```
tests/
  mas/
    unit/  api/              # hermetic, run in CI
    client_tests/            # manual scripts against a live MAS
    data/router_testset.yaml # router questions
    conftest.py  pytest.ini
  agent/
    unit/  api/  conftest.py  pytest.ini
  knowledge_store/
    unit/  api/  conftest.py  pytest.ini
  eval/                      # testset.yaml, README.md, tests of the eval and benchmark tools
  ci/                        # unittest: versions, CPU build, release images, repository wiring, notices
installer/tests/             # installer, unittest
src/services/web-client/__tests__/   # Vitest
scripts/integration-checks/          # live-stack checks, by hand
scripts/eval/run-eval.py             # evaluation runner, live stack
scripts/perf/  scripts/benchmarks/   # load tests and benchmarks
installer/smoke.py                   # end-to-end smoke test
```

**One rule:** Python tests live under `tests/<service>/`, never inside `src/`.

The one exception today is `src/services/knowledge-store/tests/test_corpus_safety.py`. CI does not run it, because the knowledge-store job only runs `tests/knowledge_store`. Move it to `tests/knowledge_store/unit/`.

---

## 4. Naming conventions

### Python

| What | Convention | Example from the repo |
|---|---|---|
| **File** | `test_<module or feature>.py`, after the module it tests | `tests/mas/unit/test_schemas.py`, `test_tracing.py`, `test_rabbitmq_tool.py` |
| **Unit or API** | Same name; the folder (`unit/` or `api/`) says which | `tests/mas/unit/test_<module>.py`, `tests/mas/api/test_<router>.py` |
| **Function** | `test_<what>_<condition>_<result>`, a sentence you can read | `test_an_uploaded_document_is_gone_from_the_list_and_the_disk` |
| **Class** (optional, to group) | `Test<Thing>` | `class TestQueueStats:` |
| **Regression test** | `test_<ATP id>_<what>`, in lower case, marked `@pytest.mark.regression`, with a docstring saying what broke, how the test checks it, and when it was found and fixed. Add a row to `docs/eip/regressions.md` | `test_f28_queue_stats_count_root_tasks_not_subtasks` |
| **Fixture** | A noun for what you get | `as_admin`, `make_client`, `mock_db` |

**Do not name tests after coverage.** `docs/contributing.md` bans new files ending in `_coverage.py`. Old ones remain, for example `tests/mas/unit/test_registry_tool_functions_coverage.py`. Name a test after the behaviour it checks.

**Regression docstring, as used in `tests/mas/api/test_tasks_routes_coverage.py`:**

```python
@pytest.mark.regression
def test_f28_queue_stats_count_root_tasks_not_subtasks(self, sqlite_session):
    """Regression F28 (B-49).

    What: the task stats counted subtasks, so Total Tasks disagreed with
    the Recent tasks list, which shows root tasks only.
    How: store one root task with two subtasks in an in-memory SQLite
    database and check the stats count one task.
    When: found in ATP v7 (18/09/2026), fixed in ff82920.
    """
```

### Markers (pytest)

These are the markers registered today. Register a new one in the service's `pytest.ini` before you use it.

| Marker | Registered in | Meaning | In CI |
|---|---|---|---|
| *(none)* | | Unit or API test: fast, no external service | Yes |
| `regression` | `tests/mas/pytest.ini` | Written for a past bug; the ATP id is in the name. Used by 4 MAS tests | Yes |
| `requires_model` | `tests/mas/pytest.ini` | Needs the MiniLM embedder on disk; skipped when it is missing, never downloads it. Used by `tests/mas/unit/test_router_model.py` | Skipped there |
| `requires_stack` | MAS, agent and knowledge-store `pytest.ini` | Needs the live Docker stack. No test uses it yet | The MAS job deselects it (`-m "not requires_stack"`) |

`regression` is registered for MAS only, so `pytest -m regression` finds MAS tests only. The agent's F25 test (`tests/agent/unit/test_consumers_coverage.py::TestResolveAttachedFiles::test_knowledge_store_ref_with_doc_id_is_resolved_by_its_doc_id`) is not marked.

### Web client (Vitest)

- File: `<module-or-component>.test.ts` or `.test.tsx` in `__tests__/` (Vitest only collects `__tests__/**/*.{test,spec}.{ts,tsx}`). Examples: `api-client.test.ts`, `use-web-socket.test.tsx`, `error-boundary.test.tsx`.
- Inside: `describe('<component or module>')` and `it('<does X> when <Y>')`.
- Regression: start the `describe` with `regression <ATP id>`, for example `describe("regression F7 navbar logout", ...)`.

---

## 5. When a test must be written

These are rules, not suggestions. The reviewer checks them before approving a PR.

1. **Every bug fix starts with a failing test** that reproduces the bug (a regression test), then the fix. Mark it and log it as in section 4. This is how we produce the "3 regressions documented" deliverable (`docs/eip/regressions.md`).
2. **Every new or changed endpoint** gets API tests for:
   - the success case
   - no token or an invalid one (401)
   - the wrong role (403)
   - invalid input (422)

   Which layer validates what, and the error format, are in [`docs/validation-and-error-handling.md`](docs/validation-and-error-handling.md).
3. **Every new piece of business logic** gets unit tests: the normal case and at least one edge case (empty, duplicate, too large, not allowed).
4. **Any change in a sensitive part** (section 1) needs tests *and* a second look from the reviewer at those tests.
5. **A web component with logic** (state, API calls, error handling) gets a Vitest test. Pure layout does not.
6. **A PR without tests for new behaviour is not approved**, unless its description says why (docs only, config, or a refactor already covered by tests).
7. **Before a release** (version rules and release checklist: [VERSIONING.md](VERSIONING.md)):
   - `installer/smoke.py` on a clean CPU machine and on a GPU machine
   - the grounding evaluation (section 6)
   - for a MINOR release, the ATP scenarios of the changed features

---

## 6. How to run the tests

Install each service's requirements and its `requirements-test.txt` (pytest and the other test tools, kept out of the images) as `.github/workflows/ci.yml` does. CI uses Python 3.13, and 3.11 for the knowledge store.

```bash
# Python, from the repository root (each service has its own pytest.ini)
bash src/infra/init-env.sh   # creates src/infra/.env only when missing, with a generated JWT_SECRET_KEY and REDIS_PASSWORD: some MAS tests read settings
pytest -c tests/mas/pytest.ini tests/mas -m "not requires_stack"
pytest -c tests/agent/pytest.ini tests/agent
pytest -c tests/knowledge_store/pytest.ini tests/knowledge_store
./scripts/test/run-all.sh                  # all three; installs bcrypt<4.0 first

# Regression tests (MAS)
pytest -c tests/mas/pytest.ini tests/mas -m regression

# Coverage, as CI measures it (MAS example; agent gate 90, knowledge store 85)
pytest -c tests/mas/pytest.ini tests/mas -m "not requires_stack" \
  --cov=src/services/mas --cov-branch --cov-fail-under=85 --cov-report=term-missing

# Evaluation set and benchmark tools (hermetic)
python -m pytest tests/eval -q -p no:cacheprovider

# CI wiring
python -m unittest discover -s tests/ci -v

# Installer
python -m unittest discover -s installer/tests -t .    # what the release workflows run
pytest installer/tests                                 # also works

# Lint, as CI runs it
pip install ruff==0.16.6
ruff check src tests scripts installer packaging

# Web client
cd src/services/web-client
npm run lint        # eslint .
npm run typecheck   # tsc --noEmit -p tsconfig.json
npm test            # vitest run
```

Use `run-all.sh`. `scripts/test/run-mas.sh`, `run-agent.sh` and `run-knowledge-store.sh` change to `scripts/` instead of the repository root, so they cannot find `tests/`.

### Known failures on Windows

Five agent tests fail on Windows only. CI runs on Linux. All are in `tests/agent/unit/test_reasoning_agents_coverage.py`:

- `test_resolve_local_model_dir_explicit` (it compares a POSIX path string)
- `test_returns_decoded_generation`
- `test_no_attn_mask_and_no_cuda_and_empty_bad_words`
- `test_decide_causal_path_no_injected_model`
- `test_decide_truncates_long_context_in_causal_path`

### Coverage

| Service | CI gate (`--cov-fail-under`, with `--cov-branch`) | Measured on 07/10/2026 |
|---|---:|---:|
| MAS | 85 % | 92.3 % |
| Agent | 90 % | 93.9 % |
| Knowledge store | 85 % | 90.0 % |

With `--cov-branch`, the percentage counts lines and branches together. What counts as code is set in `pyproject.toml` (`[tool.coverage.*]`: tests, alembic and migrations are left out). Each CI run writes a coverage table to its summary (job `coverage-summary`) and uploads the HTML reports `coverage-mas`, `coverage-agent` and `coverage-knowledge-store`.

### Grounding evaluation

`tests/eval/testset.yaml` holds 100 questions on the five documents of `demo_assets/`: 47 lookup, 22 numeric, 15 multi-hop, 10 not in the corpus (the answer must say the documents do not contain it) and 6 direct answers. An answer is correct when every `answer_patterns` regex matches; the source must be `expected_source`. Details: `tests/eval/README.md`.

`scripts/eval/run-eval.py` asks them on a live stack and writes `benchmarks/<label>-<date>.json`. Full options and the report format: `benchmarks/README.md`.

```bash
pip install httpx websockets pyyaml
python scripts/eval/run-eval.py --label eval-cpu16-standard --reference cpu16 --sample-resources
python scripts/eval/run-eval.py --mode retrieval --label eval-cpu16-retrieval   # knowledge store only, no LLM
```

- The stack must be up, with each `demo_assets/` file in the knowledge store exactly once. The runner checks this and stops otherwise.
- It logs in with `SUPER_USER_USERNAME` and `SUPER_USER_PASSWORD` from the environment, or `--username` and `--password`.
- `--label` is required.
- Compare two runs with `python scripts/benchmarks/compare-benchmarks.py BEFORE.json AFTER.json`, and only runs with the same test set version.

---

## 7. Integration checks

`scripts/integration-checks/` holds 20 files that were moved out of `tests/`. CI does not run them. Their state on 07/10/2026:

- **They are written for a live stack.** Start it first (`docker compose up -d` in `src/infra/`).
- **`pytest scripts/integration-checks/` collects nothing.** The file names (`mas-integration.py`, ...) do not match pytest's `test_*.py` pattern, and the folder has no `pytest.ini`. Its `README.md` still says that command runs them all.
- **Name each file, with its service on `PYTHONPATH`:**

  ```bash
  PYTHONPATH=src/services/mas pytest scripts/integration-checks/mas-agents-persistence.py -v
  PYTHONPATH=src/services/agent/app pytest scripts/integration-checks/agent-delegation-integration.py -v
  ```

- Ten files can also run with `python <file>` (they have a main block). `ks-upload-script.py` and `mas-task-workflow.py` hold no pytest test at all.
- **`agent-delegation-integration.py`:** 8 of its 12 tests fail against the current ReAct loop.
- **`mas-agents-persistence.py`** needs Postgres and RabbitMQ: it uses the MAS database engine, and `create_agent` declares a RabbitMQ queue.

The plan is to turn the critical ones into tests under `tests/<service>/` marked `requires_stack`.

---

## 8. What CI enforces

**`ci.yml`** runs on every pull request, on pushes to `master`, `main`, `pre-release-fix` and `Sprint#1_September2026_Tek5`, and by hand.

| Job | What it runs |
|---|---|
| `lint` | `ruff check src tests scripts installer packaging`, ruff 0.16.6 |
| `versions` | `python -m unittest discover -s tests/ci -v`, then `python scripts/ci/check-versions.py` |
| `licences` | The licence scripts' tests, `scripts/licences/third_party_notices.py --check`, then `scripts/licences/check_licences.py`: fails on GPL, AGPL or SSPL in the Python packages, the web client's production dependencies or the desktop app's crates (LGPL is a warning) |
| `cpu-build-wiring` | `python -m unittest discover -s tests/ci -p "test_cpu_torch_build.py" -v` |
| `cpu-images` | Builds the mas, agent and knowledge-store images through the CPU overlay; fails on any CUDA package or torch (`scripts/ci/check-cpu-image.py`) |
| `test-mas` | MAS tests, `-m "not requires_stack"`, coverage at least 85 % |
| `test-agent` | Agent tests, coverage at least 90 % |
| `test-knowledge-store` | Knowledge-store tests on Python 3.11, coverage at least 85 % |
| `coverage-summary` | Test and coverage tables in the run summary |

**`eval-testset.yml`** runs `pytest tests/eval -q` on the same pushes and pull requests, when the evaluation files change (section 2.6).

**`desktop-release.yml`** and **`images.yml`** run the installer tests on a `v*` tag or by hand.

| Check | Today | Target |
|---|---|---|
| `ruff check` | Yes | |
| Python tests with coverage gates (MAS 85, agent 90, knowledge store 85) | Yes | |
| Coverage table and HTML reports | Yes | Publish the numbers in the README |
| Evaluation set checks | Yes, when its files change | |
| Web client: `npm run lint`, `npm run typecheck`, `npm test` | No | Add a CI job |
| Installer tests on every PR | No (release tags only) | Add to `ci.yml` |
| `ruff format --check` | No (pre-commit only, ruff v0.6.9 there) | Add to CI |
| Type checking (mypy) | No | Start with MAS auth and new code |
| bandit | No (report run by hand) | Add to CI |
| Integration checks, grounding evaluation, smoke test | No (live stack) | Run by hand before a release |

Details of each job: "CI pipeline" in `docs/operations.md`. The workflow files remain the source of truth.

---

## 9. Test data and models

- **Only fictional data:** the five documents in `demo_assets/` and the ATP test accounts. Never real customer documents.
- **Unit and API tests mock the heavy libraries and the services.** `tests/mas/conftest.py` replaces torch, transformers and bitsandbytes and uses an in-memory SQLite database; fakeredis stands in for Redis and RabbitMQ is mocked. `tests/knowledge_store/conftest.py` replaces spaCy. Real models run only in the evaluation, the integration checks and the smoke test.
- **LLM checks test facts, not wording:**
  - the cited source file name is present
  - the key figures are present (regex patterns, `\b` before numbers)
  - out-of-corpus questions get the refusal
- **Keep the answer cache off for evaluations and timing runs.** It is off unless `AGENT_RESPONSE_CACHE` is set to `1`. Its key does not include the model file, so with the cache on a run could score answers cached for another model.
