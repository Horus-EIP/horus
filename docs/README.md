# Horus AI Documentation

One file per topic. Use Ctrl+F inside any of them — they're long on purpose.

## Engineering docs

| Topic | Read for |
|-------|----------|
| [Getting Started](getting-started.md) | Onboard a fresh clone, configure env vars, troubleshoot common issues. |
| [Architecture](architecture.md) | System overview, per-service deep dives, data model, jury-facing fiche. |
| [API Reference](api-reference.md) | MAS REST, Knowledge Store REST, and WebSocket events. |
| [Operations](operations.md) | Deployment, monitoring, secrets, environment matrix. |
| [Security & Compliance](security.md) | RBAC matrix, security audit, data protection, telemetry. |
| [Contributing](contributing.md) | Workflow, code style, commit convention, testing policy, docs audit. |
| [Demo](demo.md) | Live-demo script, copy-paste cheatsheet, post-demo action plan. |
| [Changelog](../CHANGELOG.md) | Reverse-chronological log of every commit, grouped by month. |

## EIP Tech 4 deliverables

Everything the jury looks at, grouped under [`eip/`](eip/):

| Document | Objective |
|----------|-----------|
| [EIP Index](eip/README.md) | Map of every objective → file |
| [Objectives Audit](eip/objectives-audit.md) | Current scorecard against Points 1, 2, A, D |
| [Performance](eip/performance.md) | KPIs, benchmarks, before/after results (**Point D**) |
| [Tech Watch](eip/tech-watch.md) | Sources we monitor + tech evaluation log (**Point 1**) |
| [Community Contributions](eip/community-contributions.md) | Two-way engagement with upstream projects (**Point 1**) |
| [Protection Plan](eip/protection-plan.md) | What's protected, why, how (**Point A**) |
| [Diffusion Strategy](eip/diffusion-strategy.md) | What we share publicly vs. NDA vs. internal (**Point A**) |
| [Code-vs-Docs Audit](eip/code-vs-docs-audit.md) | Historical drift audit (archived, already acted upon) |

## Reference + assets

| | |
|---|---|
| [ADRs](adr/) | Individual architecture decision records (one per file). |
| [Assets](assets/) | Presentation slides and internal research PDFs. |

Confidential material lives under `ip_protection/` and is excluded from the published site. Historical sprint notes are under `archive/` and are also excluded.

## Building the site

```bash
cd docs
mkdocs serve   # live reload at http://localhost:8000
mkdocs build   # static site under ../_docs_build/mkdocs
```

Or run `scripts/docs.sh` from the repo root to build the full documentation set (MkDocs + Python pdoc + TypeScript TypeDoc).
