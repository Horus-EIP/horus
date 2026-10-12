# Protection Plan

What's protected in Horus, why, and how — for EIP Tech 4 Objective A (Protect and Valorize Your Technology).

This is the **operational** companion to [security.md](../security.md) (which covers RBAC, audit, data protection, telemetry) and the [diffusion strategy](diffusion-strategy.md) (which covers what we share externally).

---

## Protected assets

| # | Asset | Why it's protected | How it's protected | Evidence |
|---|-------|--------------------|--------------------|----------|
| 1 | **Multi-agent orchestration logic** (MAS task routing, agent lifecycle, delegation chains) | Core commercial differentiator; novel combination of patterns not available in off-the-shelf products | Closed-source under proprietary [LICENSE](../../LICENSE); OpenTimestamps proof of authorship | `docs/ip_protection/deposit_proof/horus_mvp_v1.0.zip.ots` |
| 2 | **RAG pipeline + tool registry** (`src/services/agent/app/ai_agents/`) | Specific tool composition, ReAct prompting, and skill-routing approach | Closed-source; tracked in private repo | Source code only visible to authorised contributors |
| 3 | **Document analysis pipeline** (ContentAnalyzer, DocumentChunker, smart-search) | Proprietary chunking + entity-extraction strategy tuned for enterprise corpora | Closed-source; NDAs for any external test partner | `docs/ip_protection/nda/Horus_NDA_Template.pdf` |
| 4 | **Customer documents uploaded to Knowledge Store** | Customer-owned, sometimes regulated (finance, HR, compliance) | Self-hosted by design — data never leaves the customer perimeter; bcrypt-hashed user creds; RBAC on every endpoint; OTLP telemetry has no PII | `docs/security.md` (Data Protection section) |
| 5 | **Authentication secrets** (JWT signing key, DB password, RabbitMQ creds) | Compromise = full system takeover | Env-injected via `src/infra/.env` (gitignored); `.env.example` ships defaults; rotation playbook in `docs/operations.md` (Secrets Management) | `.gitignore` (line 5: `.env`), `src/infra/.env.example` |
| 6 | **Brand + project artefacts** (Horus name, presentation deck, jury materials) | Reputation + IP | NDA-gated distribution; greenlight assets in private repo folder | `greenlight/` directory + signed NDAs |
| 7 | **Team contributors' personal data** (emails, identifiers in NDAs) | GDPR | Stored only in signed PDFs under `docs/ip_protection/nda/`; access limited to project leads | NDAs are excluded from the public MkDocs build via `mkdocs.yml` `exclude_docs:` |

---

## Legal layer

| Mechanism | Status | Document |
|-----------|--------|----------|
| **OpenTimestamps deposit** (Bitcoin-anchored proof of authorship for MVP snapshot) | ✅ Filed | `docs/ip_protection/deposit_proof/horus_mvp_v1.0.zip.ots` + `hash_logs.png` |
| **NDA template** | ✅ Ready to send | `docs/ip_protection/nda/Horus_NDA_Template.pdf` |
| **Signed NDAs — team members** | ✅ Matheus Lopez, Noah Gibelli | `docs/ip_protection/nda/Horus_NDA_Matheus_Lopez.pdf`, `Horus_NDA_Noah_Gibelli.pdf` |
| **Signed NDAs — external beta testers** | ⚠️ To collect before each external test | Use the template |
| **Proprietary licence v2.1** (all rights reserved; use only under a commercial, evaluation or contributor agreement; EU-mandatory rights kept; licence keys; `opensource/horus-bench-kit/` left to its own Apache-2.0 licence) | ✅ In repo (08/10/2026) | [LICENSE](../../LICENSE); justification in [ADR-004](../adr/ADR-004-closed-source-licence.md) and [ADR-007](../adr/ADR-007-open-source-benchmark-kit.md) |
| **Dependency licence inventory** (1,463 third-party components; all compatible with closed source) | ✅ Done (26/09/2026) | [dependency-licence-inventory.xlsx](dependency-licence-inventory.xlsx) |
| **Contributor Agreement** (confidentiality + rights assignment + credit) | ⚠️ To write before the first external contributor | — |
| **Evaluation Licence** (90 days, non-production, confidential) | ⚠️ To write before the next external test | — |
| **THIRD_PARTY_NOTICES** (licence texts of the shipped components) | ✅ Generated (07/10/2026), checked in CI, shipped in the release ZIP | [THIRD_PARTY_NOTICES](../../THIRD_PARTY_NOTICES), [LICENSES/](../../LICENSES/), [NOTICES/](../../NOTICES/) |
| **Time-limited licence key** | 🗓 Planned (ADR-004) | — |

> **Verification:** any holder of the original `horus_mvp_v1.0.zip` archive can run `ots verify horus_mvp_v1.0.zip.ots` to confirm the snapshot existed on the date encoded in the proof.

---

## Technical layer

Mapped to the protected assets above:

| Control | Implementation | Covers asset |
|---------|----------------|--------------|
| **Bcrypt password hashing** (cost factor 12) | `src/services/mas/auth/auth_tool_functions.py:24` | #5 |
| **JWT short-lived tokens + refresh** | `src/services/mas/auth/auth_tool_functions.py:95,125` | #5 |
| **Four-tier RBAC** (Admin / Manager / User / System) | `src/services/mas/auth/permissions.py` | #1, #2, #3, #4 |
| **Per-route permission checks** (FastAPI `Depends`) | All routes in `src/services/mas/*/routes.py` | #1, #2, #3, #4 |
| **Network segregation** (services on `horus-net` internal Docker network only) | `src/infra/docker-compose.yml` | #1, #2, #3, #4 |
| **Secrets in env, not code** | `src/infra/.env` gitignored; `.env.example` for shape | #5 |
| **Structured JSON logs with correlation IDs** (no PII in log payloads) | `src/services/mas/core/structured_logging.py`, `correlation_middleware.py` | #4 |
| **Container-only persistence** (Postgres, Redis, ChromaDB, Tempo) — no host mounts of customer data | `src/infra/docker-compose.yml` volumes | #4 |
| **OTel telemetry scrubs request bodies by default** | OTel auto-instrumentation config in `src/services/*/core/tracing.py` | #4 |
| **Pre-commit hooks** (ruff, docstring length) | `.pre-commit-config.yaml` | All — prevents accidental secret leaks via convention enforcement |

---

## Security review status

| Check | Tool | Status | Output |
|-------|------|--------|--------|
| Static analysis (style + bugs) | Ruff | ✅ Run regularly | `greenlight/code-quality-review/ruff_report.txt` |
| Static analysis (legacy) | Pylint | ✅ Run regularly | `greenlight/code-quality-review/pylint_report.txt` |
| Test coverage | pytest --cov | ✅ ≥70% on every Python service | `greenlight/code-quality-review/coverage_{agent,ks,mas}/` |
| Security-focused SAST | **Bandit** | ⚠️ To run before jury | Command: `bandit -r src/services/mas src/services/agent src/services/knowledge-store -f txt -o greenlight/code-quality-review/bandit_report.txt -ll` |
| Dependency vulnerability scan | **pip-audit** | ⚠️ To run before jury | Command: `pip-audit -r src/services/mas/requirements.txt && pip-audit -r src/services/agent/requirements.txt && pip-audit -r src/services/knowledge-store/requirements.txt` |
| Container scan | **Trivy** | ⚠️ Optional, before jury | Command: `trivy fs src/services/` |

---

## What we will not do

- **Open-source any part of Horus.** The whole product stays closed ([ADR-004](../adr/ADR-004-closed-source-licence.md)); see the [diffusion strategy](diffusion-strategy.md) for what we do share.
- **Ship a hosted version.** Horus is self-hosted by design — that's both a feature and a protection.
- **Accept any external contribution without an NDA + Contributor Agreement.** There is no public repository: contributors are invited to the private repo (ADR-004).

---

## Review

- **Owner:** Loup Marquez (project lead)
- **Last review:** 26/09/2026 (licence decision, ADR-004)
- **Next review:** before each EIP milestone and before any external demo
- **Linked docs:** [security.md](../security.md) · [diffusion-strategy.md](diffusion-strategy.md) · [ADR-004](../adr/ADR-004-closed-source-licence.md) · [ADRs](../adr/)
