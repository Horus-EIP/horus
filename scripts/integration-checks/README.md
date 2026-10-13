# Integration checks

Tests that need a **live Docker stack** to run. They are no longer part of the default `pytest` suite (per `tests/TESTING_PLAN.md`); CI does not execute them.

Run them manually after `docker compose up -d` from `src/infra/`:

```bash
# All of them
pytest scripts/integration-checks/ -v

# One at a time
pytest scripts/integration-checks/mas-integration.py -v
pytest scripts/integration-checks/mas-beta-criteria.py -v
```

These files use the same imports they did when they lived under `tests/`. Many call real endpoints over HTTP, real WebSockets, real RabbitMQ — adjust the base URL via env vars (`TEST_BASE_URL=http://localhost:8000`, etc.).

| File | What it proves |
|------|----------------|
| `mas-integration.py` | MAS end-to-end (auth, tasks, conversations, chat) against a live server |
| `mas-beta-criteria.py` | The 24 success criteria (F1-F24) from the beta test plan (`beta_test_plan.md`, in the team's private repository) |
| `mas-beta-integration.py` | Beta integration scenarios |
| `mas-task-workflow.py` | Task lifecycle through RabbitMQ + Agent |
| `mas-task-cancellation.py` | Task cancellation through the running orchestrator |
| `mas-agent-heartbeat.py` | Agent registration + heartbeat against running MAS |
| `mas-observability.py` | Prometheus + Tempo + Loki endpoints |
| `mas-db-models.py` | ORM models against a real Postgres |
| `mas-schemas-integration.py` | Schema validation against live data |
| `agent-delegation-handler.py` | Inter-agent delegation through RabbitMQ |
| `agent-delegation-integration.py` | Multi-agent delegation chain |
| `agent-csv-integration.py` | CSV ingestion through the live Agent service |

If you only need fast feedback on the code, run `pytest` from the repo root instead — that suite is fully hermetic.
