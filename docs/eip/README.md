# EIP Tech 4 — Jury Deliverables

This folder is the **single index** for everything the EIP Technical Track jury will look at. Each Markdown file here corresponds directly to a numbered/lettered objective in the *Technical Track Student Guide — Tech 4 (2025/2026)*.

If you arrived here from the MkDocs sidebar or a jury hand-out, start with [objectives-audit.md](objectives-audit.md) — it scores us against every required deliverable.

---

## Map: objective → document

| Objective | What the guide asks for | Where it lives |
|-----------|--------------------------|----------------|
| **1 — Tech Watch** | Active monitoring, comparative briefs, POCs, decision rationale, community engagement | [tech-watch.md](tech-watch.md) + [community-contributions.md](community-contributions.md) + [../adr/](../adr/) + [../assets/research/](../assets/research/) + [../../CHANGELOG.md](../../CHANGELOG.md) |
| **2 — Structure, document, harden the architecture** | Clear architecture, complete README, quality + reliability + minimal security | [../README.md](../README.md) + [../architecture.md](../architecture.md) + [../operations.md](../operations.md) + [../../CONTRIBUTING.md](../../CONTRIBUTING.md) + [../contributing.md](../contributing.md) + [../security.md](../security.md) + [../../greenlight/code-quality-review/](../../greenlight/code-quality-review/) |
| **A — Protect and valorize the technology** | Legal protection, technical protection, security review, valorization | [protection-plan.md](protection-plan.md) + [diffusion-strategy.md](diffusion-strategy.md) + [../security.md](../security.md) + [../ip_protection/](../ip_protection/) (NDAs + OTS proof — not in published site) |
| **D — Measure, test, optimize performance** | KPIs, load/stress tests, before/after, dashboards, analysis | [performance.md](performance.md) + [../../scripts/perf/](../../scripts/perf/) + [../../greenlight/grafana-screenshots/](../../greenlight/grafana-screenshots/) |

---

## Files in this folder

| File | What it is | Status |
|------|------------|--------|
| [objectives-audit.md](objectives-audit.md) | **Start here.** Scorecard of every required deliverable across the four objectives, with file:line evidence and a checklist of what (if anything) remains to run. | Live — re-run after each milestone |
| [tech-watch.md](tech-watch.md) | Sources we follow, technologies evaluated (adopted / trialed / rejected / watching), review cadence. | Live |
| [community-contributions.md](community-contributions.md) | Log of upstream contributions + three ready-to-post issue drafts. | Add real link before jury |
| [protection-plan.md](protection-plan.md) | Seven-asset protection inventory, legal + technical layers, SAST checklist. | Run bandit before jury |
| [diffusion-strategy.md](diffusion-strategy.md) | Three-tier visibility model (public / NDA / internal), per-asset decision matrix, open-source posture. | Live |
| [reproducibility-test.md](reproducibility-test.md) | Protocol and form for someone outside Epitech who installs Horus from the readme and the installer (B-39). | Fill in after the test |
| [performance.md](performance.md) | KPIs (K1 chat p95, K2 RAG precision@5, K3 read throughput) with targets, benchmark scripts, optimization log. | Fill in numbers after the A/B run |
| [code-vs-docs-audit.md](code-vs-docs-audit.md) | Historical audit (May 2026) of documentation drift against the codebase. Findings were addressed. Kept as evidence of process rigor. | Archived — already acted upon |
| [Technical-Track-Student-Guide-Tech-4.pdf](Technical-Track-Student-Guide-Tech-4.pdf) | Official EIP guide we are graded against. Kept here for reference and to anchor the objectives-audit cross-refs. | Reference |

---

## Files referenced from here that live elsewhere

These are working artifacts the jury will want to see, but they belong in the locations where the team naturally uses them:

| Artifact | Why it's not in this folder | Where to find it |
|----------|----------------------------|------------------|
| `CHANGELOG.md` | Convention dictates root-of-repo so GitHub renders it; tooling expects it there | [../../CHANGELOG.md](../../CHANGELOG.md) |
| `CONTRIBUTING.md` | At the root of the repo, so GitHub shows it next to issues and pull requests | [../../CONTRIBUTING.md](../../CONTRIBUTING.md) |
| ADRs | Industry-standard pattern is one file per decision under `docs/adr/` | [../adr/](../adr/) |
| Research dossiers (5 PDFs) | Binary assets grouped with presentation slides | [../assets/research/mas/](../assets/research/mas/) |
| Signed NDAs + OpenTimestamps proof | Confidential — `ip_protection/` is excluded from the published MkDocs site | [../ip_protection/](../ip_protection/) |
| Performance benchmark scripts | Run from the repo, not read like prose | [../../scripts/perf/](../../scripts/perf/) |
| Code-quality reports (ruff, pylint, coverage) | Generated outputs grouped with greenlight materials | [../../greenlight/code-quality-review/](../../greenlight/code-quality-review/) |
| Greenlight slide deck + tech brief | EIP milestone-specific artifacts | [../../greenlight/](../../greenlight/) |
| Comparative tech brief (`.docx`) | Word format for jury hand-out, not for the web site | [../../greenlight/track-objectives-report/Comparative_Tech_Brief.docx](../../greenlight/track-objectives-report/Comparative_Tech_Brief.docx) |

---

## Maintenance

- Review and update [objectives-audit.md](objectives-audit.md) before every EIP milestone (greenlight, beta, final defence).
- The four `.md` files in this folder are *living* documents — keep them current as the project evolves.
- `code-vs-docs-audit.md` is a frozen snapshot; do not edit, generate a new one if needed.
