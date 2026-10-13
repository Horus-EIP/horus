# Documentation Audit Report

**Date:** 2026-05-29
**Scope:** All Markdown docs under `/docs`, root-level docs, and `greenlight/*.md` (now in the team's private repository)
**Source-of-truth:** `src/` code, `src/infra/docker-compose.yml`, `src/infra/.env.example`, `pyproject.toml`, `package.json`, `scripts/`
**Method:** Five parallel Explore subagents read every in-scope doc and verified claims against the code with file:line citations.

---

## TL;DR

- **Two critical contradictions** that will silently break things:
  1. **RBAC matrix vs. WebSocket auth** — `docs/security/rbac.md` says managers can `task:read`, but `src/services/mas/auth/permissions.py:56-66` does not grant `TASK_READ` to MANAGER, and the chat WebSocket at `src/services/mas/chat/routes.py:55` enforces `TASK_READ`. **Managers cannot use chat. Either fix the code or fix the matrix.**
  2. **Jaeger referenced in three docs but does not exist** in `src/infra/docker-compose.yml`. Only Tempo is deployed. References will dead-end during a live demo.
- **One systemic naming drift:** docs reference DB user `horus` / DB name `horus_db`, but `.env.example` and compose use `postgres` / `mas_db`.
- **One stack version drift:** README claims Python 3.13; `pyproject.toml:2` targets `py311`.
- **API docs miss ~7 MAS endpoints** that exist in code (tasks, analytics, suggest-skills).
- Most architecture and ADR docs are accurate. Compliance/data-protection is accurate.

---

## Top 10 fixes (do these first)

| # | Severity | Fix | Evidence |
|---|----------|-----|----------|
| 1 | **HIGH** | RBAC matrix in `docs/security/rbac.md:112`: change Manager `task:read: Yes` → `No` **OR** add `TASK_READ` to MANAGER set in `src/services/mas/auth/permissions.py:56-66` | `permissions.py:56-66` vs `rbac.md:112,127` |
| 2 | **HIGH** | Remove Jaeger references in `docs/demo/demo-guide.md:14`, `docs/demo/copy-paste-cheatsheet.md:124`, README (architecture diagram is fine — Tempo is real) | `docker-compose.yml` has no `jaeger` service; `tempo` exists at line ~348 |
| 3 | **HIGH** | Fix Postgres examples in `docs/operations/environment-matrix.md:100,139` and `docs/getting-started/troubleshooting.md:100,139`: `-U horus -d horus_db` → `-U postgres -d mas_db` | `.env.example:64` `POSTGRES_DB=mas_db` |
| 4 | **MED** | `README.md:29` — change "Python 3.13" → "Python 3.11" | `pyproject.toml:2` `target-version = "py311"` |
| 5 | **MED** | `docs/security/security-audit.md:88` — User role `user:read` matrix value is wrong | `permissions.py:68` USER role includes `Permission.USER_READ` |
| 6 | **MED** | `docs/api/mas-api.md` — add 6 missing endpoints (see API section below) | `tasks/routes.py:428,472,537,1382`, `analytics/routes.py:48` |
| 7 | **MED** | `docs/operations/monitoring.md:61,69` — Prometheus config path is `src/infra/prometheus.yml`, not `src/infra/grafana/prometheus.yaml` | `prometheus.yml` is at infra root |
| 8 | **MED** | `docs/getting-started/onboarding.md:91` — clarify Prometheus/Grafana/Tempo are opt-in via `--profile observability` | `docker-compose.yml:366` `profiles: ["observability"]` |
| 9 | **LOW** | `docs/architecture/overview.md:499` — remove TanStack Query from stack | `package.json:27,53` only has `@tanstack/react-form` |
| 10 | **LOW** | `docs/architecture/knowledge_store_client.md` table — fetch_for_rag/list_inventory method names don't match actual `query()`/`smart_search()`/`resolve_by_filename()` | `agent/app/ai_agents/knowledge_store_client.py:120-491`, `knowledge-store/app/api/routes/store.py:69-90` |

---

## Findings by area

### Architecture & ADRs

| Doc | Status | Issue |
|-----|--------|-------|
| `architecture/overview.md` | NEEDS_UPDATE | TanStack Query listed but not installed (`package.json:27,53`). |
| `architecture/data-model.md` | OK | ORM models match docs (`db/models/conversations.py`, `messages.py`, `tasks.py`). |
| `architecture/data_extraction.md` | NEEDS_UPDATE | Doc says spaCy fallback is "regex-only"; actual code tries `en_core_web_trf` → `en_core_web_sm` → MagicMock, no regex path (`agent/app/ai_agents/data_extractor_tool.py:62-87`). |
| `architecture/agent_service.md` | OK | ReAct loop constants `MAX_REACT_STEPS=5`, `DEFAULT_TIMEOUT_SECONDS=120` confirmed. |
| `architecture/mas_service.md` | OK | Service config and WebSocket structure match. |
| `architecture/knowledge_store_client.md` | NEEDS_UPDATE | Method/route table is wrong: doc lists `fetch_for_rag → POST /search` and `list_inventory → GET /files`; actual is `query → GET /` (with params), `smart_search`, `resolve_by_filename`, `__call__` (`agent/app/ai_agents/knowledge_store_client.py:120-491`, `knowledge-store/app/api/routes/store.py:69-90`). |
| `architecture/ephemeral-conversation-agents.md` | OK | Design doc; gap with current pooled model is acknowledged. |
| `ADR-001-rabbitmq.md` | OK | Status Accepted, reflected in code. |
| `ADR-002-chromadb.md` | OK | Active. |
| `ADR-003-fastapi.md` | OK | Active across all three services. |

### API reference

| Doc | Status | Issue |
|-----|--------|-------|
| `api/mas-api.md` | NEEDS_UPDATE | Missing endpoints in doc (all confirmed in code): `GET /tasks/conversation/{conversation_id}/running` (`tasks/routes.py:428-468`), `GET /tasks/{task_id}` (`tasks/routes.py:472-518`), `POST /tasks/suggest-skills` (`tasks/routes.py:537-560`), `POST /tasks/task-step/` (`tasks/routes.py:1382-1483`), `GET /analytics/overview` (`analytics/routes.py:48-71`). Also: `POST /tasks/new_task/` response section omits the "decomposed" response variant (`tasks/routes.py:574-706`). |
| `api/knowledge-store-api.md` | OK (minor) | One undocumented endpoint: `GET /file/resolve` (`file.py:44`). |
| `api/websocket-api.md` | OK | `WS /chat/{conversation_id}/` matches `chat/routes.py:27-109`. All message types accurate. |

### Operations & getting-started

| Doc | Status | Issue |
|-----|--------|-------|
| `operations/deployment.md` | NEEDS_UPDATE | References `requirements-cpu.txt` — the file exists at `src/services/mas/requirements-cpu.txt` but is used only by `ci.yml` and `scripts/docs.sh`, not by any Dockerfile. Python version claim doesn't match `pyproject.toml:2 py311`. |
| `operations/monitoring.md` | NEEDS_UPDATE | Wrong Prometheus config path on lines 61, 69 — should be `src/infra/prometheus.yml` (file is at infra root, not under `grafana/`). |
| `operations/secrets-management.md` | OK | High-level; no specific claims that fail. |
| `operations/environment-matrix.md` | NEEDS_UPDATE | DB examples use `horus` / `horus_db` — actual is `postgres` / `mas_db` (`.env.example:64`). |
| `getting-started/onboarding.md` | NEEDS_UPDATE | Implies Prometheus is in default stack; it's behind `--profile observability` (`docker-compose.yml:366`). |
| `getting-started/configuration.md` | NEEDS_UPDATE | References `src/services/mas/core/config.py` import pattern not verified against actual code (may use legacy `pydantic.BaseSettings` instead of `pydantic_settings`). |
| `getting-started/troubleshooting.md` | NEEDS_UPDATE | Same `horus_db` / `horus` user error as environment-matrix; also references `/rabbitmq/heartbeat` endpoint that may not exist. |

### Security & compliance

| Doc | Status | Issue |
|-----|--------|-------|
| `security/rbac.md` | **NEEDS_UPDATE (CRITICAL)** | Matrix says Manager has `task:read`; permissions.py:56-66 disagrees. The doc itself contradicts the same page (line 127). Manager chat access is broken because chat WS enforces `TASK_READ` (`chat/routes.py:55`). |
| `security/security-audit.md` | NEEDS_UPDATE | User role `user:read: No` in matrix is wrong — code grants USER_READ (`permissions.py:68`). |
| `compliance/data_protection.md` | OK | Cascade-delete, bcrypt hashing, SET NULL on user delete all confirmed. |
| `compliance/telemetry.md` | NEEDS_UPDATE | Claims Jaeger backend; code uses generic OTLP exporter (`mas/core/tracing.py:26`). Metrics inventory incomplete vs `mas/core/metrics.py`. |
| `compliance/architecture_fiche.md` | OK | Components, stack, auth flow, RBAC enforcement all match code. |

### README, root, contributing, demo

| Doc | Status | Issue |
|-----|--------|-------|
| `README.md` | NEEDS_UPDATE | Python 3.13 → 3.11; check Next.js minor version label. |
| `beta_test_plan.md` (now in the team's private repository) | OK | Module ID and F1-F24 structure align with implemented API. |
| `docs/README.md` | OK | Index links resolve. |
| `contributing/contributing.md` | OK | Branch naming, pytest commands match real `pytest.ini` paths. |
| `contributing/code_style.md` | OK | Minor: references `docs/architecture/adr/` subdir but ADRs are flat in `architecture/`. |
| `contributing/commit-convention.md` | LOW | Symbol legend slightly diverges from `contributing.md` — cosmetic. |
| `contributing/testing-policy.md` | OK | Scripts and CI workflow paths verified. |
| `contributing/workflow.md` | OK | High-level. |
| `demo/demo-guide.md` | NEEDS_UPDATE | Jaeger URL on line 14; clarify working directory (`src/infra/` for compose). |
| `demo/copy-paste-cheatsheet.md` | NEEDS_UPDATE | Jaeger URL on line 124. |
| `demo/post-demo-action-plan.md` | OK | Prescriptive plan, not a description. |

---

## Cross-cutting findings

1. **Jaeger ghost** — three docs mention Jaeger; no `jaeger:` service in compose. Either drop the references or add the service (Tempo already covers OTLP traces).
2. **DB naming drift** — `horus` / `horus_db` appears in ops + troubleshooting docs but contradicts `.env.example` (`postgres` / `mas_db`). Find/replace across all docs.
3. **Python version drift** — README says 3.13 while `pyproject.toml` targets `py311`. Pick one and align.
4. **Observability profile** — docs treat Prometheus/Grafana/Tempo as always-on; compose puts them behind `profiles: ["observability"]`. Either remove the profile gate (and document defaults) or update the docs to say `docker compose --profile observability up`.
5. **RBAC source of truth** — `permissions.py` is the only thing routes consult. The matrix in two docs has drifted. Consider generating the matrix from the enum at build time.

---

## What's intentionally NOT audited

- `docs/archive/**` (frozen historical content, now in the team's private repository)
- `docs/ip_protection/**` (legal docs, not technical, now in the team's private repository)
- PDFs, pptx, docx
- `docs/contributing/mas/README_PROJECT.md` (out of audit scope — service-specific)

## Recommended next pass

After fixing the top 10, run the same audit prompt (`docs/contributing/docs-audit-prompt.md`) in Claude Code. It will re-check and produce a clean follow-up report.
