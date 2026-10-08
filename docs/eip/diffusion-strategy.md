# Diffusion Strategy

What we share, what stays closed, and why. Companion to the [protection plan](protection-plan.md).

---

## Three tiers of visibility

| Tier | What's in it | Audience |
|------|--------------|----------|
| **Public** | README · architecture overview · API reference shape (not internals) · presentation deck · marketing materials | Anyone — recruiters, partners, jury (without NDA), online viewers |
| **Restricted (NDA)** | Source code · ADRs · per-service deep dives · benchmark numbers · roadmap | Beta-test customers · prospective partners · investors · jury members during evaluation |
| **Internal only** | Signed NDAs · IP deposit proofs · customer data · production secrets | Core team + EIP coordinator |

---

## Decision matrix

| Asset | Tier | Channel | Rationale |
|-------|------|---------|-----------|
| `README.md` | Public | GitHub (if/when public) | Standard entry point; reveals stack, not secrets |
| Architecture diagram (mermaid in README) | Public | GitHub, slide deck | Component-level only; no proprietary logic exposed |
| Presentation deck (`docs/assets/horus_presentation_v8.pdf`) | Public | Hand-out during pitches | Marketing-grade content, no implementation details |
| MkDocs site | Restricted | Self-hosted (not GitHub Pages) for now; URL shared to authorized viewers only | Aggregates internals; published only behind auth |
| Tech fiche / one-pager | Public | PDF for recruiters / partner emails | Distilled value proposition |
| Beta test plan (`beta_test_plan.md`) | Restricted | Sent to beta partners after NDA | Reveals testing scope and current limits |
| Source code | Restricted (will stay closed) | Private GitHub repo + branch protection | Core IP per [protection plan](protection-plan.md) |
| ADRs (`docs/adr/`) | Restricted | Shared in technical interviews with the jury / partners | Demonstrates engineering rigor; reveals chosen architecture |
| Research papers (`docs/assets/research/mas/`) | Restricted | Shared on request | Team's own work; not for public republication |
| Performance numbers (`docs/performance.md` + benchmark outputs) | Public (summary) / Restricted (raw) | Summary in the tech fiche; raw under NDA | Aggregate KPIs make us look good; raw data could leak optimization tricks |
| Greenlight materials (`greenlight/`) | Restricted | EIP jury + Epitech only | Course deliverables, not for outside circulation |
| Signed NDAs | Internal only | Excluded from public site via `mkdocs.yml exclude_docs` | Contains counterparties' personal information |

---

## Active channels

| Channel | Purpose | Status |
|---------|---------|--------|
| **Private GitHub repo** (EpitechPromo2027/G-EIP-600-…) | Source of truth, version control, CI | ✅ Active |
| **Self-hosted MkDocs** (planned URL: `docs.horus.internal`) | Restricted-tier documentation portal | ⚠️ To deploy before jury |
| **EIP jury submission portal** | Greenlight / beta / final defence deliverables | ✅ Used per milestone |
| **Live demo environment** | Show running stack to partners under NDA | ✅ Local + on-demand |
| **Pre-recorded demo video** | Public, marketing | ⚠️ To produce before jury |
| **One-page tech fiche** | Recruiter / partner hand-out | ⚠️ To generate (script: `scripts/docs.sh` + pandoc) |

---

## What we will publish (and when)

| Item | When | Where |
|------|------|-------|
| Tech-fiche PDF | Before EIP greenlight | Public link in README |
| Marketing demo video | Before EIP greenlight | Public, YouTube unlisted |
| Public website (landing only — value prop + contact form) | Q3 2026 | Static site, separate domain |
| One blog post per technology adoption (RabbitMQ, ChromaDB, Tempo) | After each ADR | Public — Medium/Dev.to |
| Open-source benchmark and evaluation kit (`opensource/horus-bench-kit/`) | Done 08/10/2026: Apache-2.0 ([ADR-007](../adr/ADR-007-open-source-benchmark-kit.md)), outside the Software as defined by [LICENSE](../../LICENSE) v2.1 section 1. Nothing else is opened ([ADR-004](../adr/ADR-004-closed-source-licence.md)) | `opensource/horus-bench-kit/` (shared as a zip) |

## What we will NOT publish

- Source code of the orchestrator, agent core, or knowledge-store internals.
- Customer documents or any derivative thereof.
- Specific performance numbers that reveal optimization tricks (only aggregate ranges go public).
- Internal sprint notes or roadmap commitments.
- Prompt engineering / instruction templates we use for the decision agent.

---

## Open-source posture

**Decision (24/09/2026): Horus is fully closed source** under the proprietary [LICENSE](../../LICENSE) (v2.1). The full justification (business model, protection, dependency licences, alternatives rejected) is in [ADR-004](../adr/ADR-004-closed-source-licence.md). In short:

- The orchestration and document-analysis logic is the commercial moat.
- Self-hosting is the customer promise; an open core would not change customer behaviour but would forfeit the moat.
- One isolated utility is open: the benchmark and evaluation kit in `opensource/horus-bench-kit/`, under Apache-2.0 ([ADR-007](../adr/ADR-007-open-source-benchmark-kit.md)); it contains no Horus code and section 1 of LICENSE v2.1 leaves it out of the Software. Opening anything else is not planned.
- External contributions happen **by invitation**, under an NDA + Contributor Agreement, in the private repository.

If we re-evaluate, the trigger conditions are:
1. A clear partner commitment to community maintenance.
2. A separation of the core into a permissively-licensable "engine" layer + a proprietary "product" layer.

Neither is true today.

---

## Review

- **Owner:** Loup Marquez
- **Last review:** 26/09/2026 (licence decision, ADR-004)
- **Linked docs:** [protection-plan.md](protection-plan.md) · [security.md](../security.md) · [LICENSE](../../LICENSE) · [ADR-004](../adr/ADR-004-closed-source-licence.md) · [ADR-007](../adr/ADR-007-open-source-benchmark-kit.md)
