# Testing policy

## Scope

The Horus system is tested across Python services (MAS first), with CI running selected suites on every push and pull request.

## Types of tests

| Type | Status | Description |
|------|--------|-------------|
| Unit tests | Active | MAS core logic and APIs under `tests/mas/` (see CI for exclusions) |
| Integration tests | Active | `tests/mas/test_integration.py` against a running MAS instance (CI job `test-integration`) |
| End-to-end tests | Planned | Full stack including web client |
| Performance tests | Planned | Agent latency, RAG throughput |
| Security tests | Planned | Authorization, access control, data handling |

## Tools

- `pytest`, `pytest-asyncio`, `httpx`, `websockets` for Python  
- `coverage.py` where enabled locally (e.g. `scripts/python/mas/test_code.sh`)  
- GitHub Actions — `.github/workflows/ci.yml` at the repository root  

## Coverage goals

- Short term: maintain meaningful coverage on new MAS code paths touched by tests  
- Longer term: raise coverage on orchestration, auth, and task flows as suites grow  

## Example commands

```bash
# From repository root
pytest -c tests/mas/pytest.ini tests/mas -v

bash scripts/python/mas/test_code.sh
```

## Continuous testing

CI runs on each push and pull request; see the workflow file for Python version, infra services started with Docker Compose, and exact pytest invocations.
