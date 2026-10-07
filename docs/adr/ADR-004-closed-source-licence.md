# ADR-004: Horus stays fully closed source under a proprietary licence

**Date:** 2026-09-24
**Status:** Accepted by the team (24/09/2026). Sent to the study supervisor for validation of the fully closed scope (Tek5 Objective 1, due 30/09/2026).
**Last updated:** 2026-09-26
**Deciders:** Loup Marquez-Luttringer, Noah Gibelli, Matheus Lopez
**Related:**

- `LICENSE` (Horus Proprietary Software Licence v2)
- `docs/eip/dependency-licence-inventory.xlsx`
- `docs/eip/protection-plan.md`
- `docs/eip/diffusion-strategy.md`

> This ADR is an engineering and business decision record, not legal advice. Have a lawyer review the commercial licence texts before the first paid contract.

---

## Context

### How we plan to sell Horus

Source: the pitch deck (`docs/eip_pool_tek5/Horus_Pitch_Demo.pptx`, Sept 2026).

- **Product.** A private AI assistant that runs **on the customer's own servers**, works fully offline, and answers from the company's documents with sources (slides 1 and 3). It is delivered as one ZIP plus a desktop app.
- **Revenue line 1: a recurring licence, billed per quarter, per site** (slide 6). Updates, support and the desktop app are included.

  | Tier | Users | Price |
  |---|---|---|
  | Starter | up to 25 | €1,500 / quarter |
  | Team | up to 100 | €4,500 / quarter |
  | Enterprise | unlimited, several sites | on quote |

- **Revenue line 2: AI-box rental.** €300/month for a DGX Spark–class machine that we set up and replace (slide 6).
- **Target.** 200 mid-size regulated companies in France and neighbouring countries by 2028, about €2M ARR (slide 5). Pilots come first: *"3 pilot companies… to run Horus for a quarter"* (slide 9).
- **Positioning** (slide 7): *"Horus is not a better model. It is the product around the model: install, users, documents, sources, all on your hardware."* The open alternatives (LangChain, CrewAI, MetaGPT) are toolkits. Horus is the finished product.
- **Roadmap** (slide 9): an agent marketplace where customers build and share agents, inside a company or across companies.

### What this means for the licence

1. **The customer holds a copy.** Horus is self-hosted, so every customer physically has the software. Unlike SaaS, the code is not protected by staying on our servers. It is protected by the **licence plus the contract**, plus the technical measures below.
2. **The value is in our code, not in the model.** The installer, the multi-agent orchestration, the document pipeline, RBAC and grounding are what customers pay for. The models themselves are free (Apache-2.0 / MIT).
3. **Revenue depends on companies being unable to run Horus without paying.** Any licence that lets a company self-host Horus for free for internal use removes the revenue line.

### What existed before this decision

- `LICENSE` (v1): the *HORUS AI Proprietary Software License Agreement* (2025). All rights reserved, with the 3 of us as licensors.
- `protection-plan.md`: 7 protected assets. The core ones are #1 MAS orchestration, #2 the RAG pipeline and tool registry, and #3 the document-analysis pipeline.
- `diffusion-strategy.md`: 3 visibility tiers. Source code is "Restricted – will stay closed".
- Signed team NDAs, an NDA template, and an OpenTimestamps proof of the MVP.

### The Tek5 requirement

Objective 1 (mentor follow-up, 19/09/2026):

- *"Decide open or closed source and the exact scope… and have it validated by the study supervisor."*
- *"Choose the licence, add it to the repository, and write the justification: why this scope, why this licence, what it implies for users and contributors."*

The mentor mentioned partial opening (agent open, MAS closed) as *one valid option*. The mentor also warned that if a large part stays closed, the "find contributors" objective loses its basis. This ADR answers both points.

---

## Decision

### 1. All of Horus stays closed source

This covers:

- the MAS orchestrator, agent service, knowledge store and web client
- the desktop app, installer, packaging and scripts
- the documentation

No part is released under an open-source licence. The only code under open licences in the product is **third-party dependencies**, used under their own licences (see the inventory).

### 2. Licence choice: a proprietary licence framework made of four documents

| Document | Who gets it | What it does | Status |
|---|---|---|---|
| **Horus Proprietary Licence v2** (repo `LICENSE`) | Anyone who gets a copy (repo, ZIP, AI box) | All rights reserved. No right to use without a signed agreement. Covers source, binaries, images and docs. Respects EU mandatory rights. Points to third-party notices. | ✅ In the repo (`LICENSE`) |
| **Horus Commercial Licence Agreement** (EULA + order form) | Paying customers | Per-site, per-quarter subscription with a user cap (Starter / Team / Enterprise). Internal use on the customer's infrastructure only. Includes updates and support. No redistribution, hosting for others, or modification. Customer data stays the customer's. | To write before the first paid pilot |
| **Horus Evaluation Licence** | Pilots, beta testers, jury, partners | Free, time-limited (default 90 days = one pilot quarter), non-production, confidential. We may use their feedback. | To write before the next external test |
| **Contributor Agreement + NDA** | Anyone outside the three of us who touches the code (external contributors, beta testers who send patches) | Confidentiality, plus assignment (or exclusive licence) of their contribution's rights to the Horus owners, and credit. | NDA exists; contributor agreement to write |

### 3. Why this framework and not a single off-the-shelf licence

Standard licence texts (MIT, GPL, BUSL, Elastic, PolyForm…) are designed for code that is **published**. We do not publish Horus. For software sold to companies and installed on their premises, the market standard is a proprietary licence (EULA) plus a commercial agreement per customer. Our customers' legal teams already expect this.

We keep the existing `LICENSE` as the base and fix its gaps (see "Changes from the previous LICENSE (v1)" below).

---

## Why fully closed

### 1. Business: the licence is the product

- **Every euro of revenue comes from the per-site licence.** Once the code is public under any open licence (MIT, Apache, GPL or AGPL), a company can install Horus internally for free. Self-hosting for internal use is exactly what our customers do.
- **Open source adds nothing to our customers' buying decision.** Our customers get privacy from **self-hosting**, not from reading the code. What they buy is a finished, supported product with a vendor who is accountable.
- **Opening the code would give away our differentiator.** Open toolkits already exist (slide 7). What makes us different is the finished product.
- **Clean, closed IP is an asset.** Pilots, a hardware partner (slide 9), investors or an acquirer value a codebase whose rights belong clearly to the company.
- **The marketplace (roadmap) needs control.** If agents are shared across companies, we have to control what runs on the platform and on what terms. A closed platform with its own marketplace terms fits that.

### 2. Protection: nobody builds a product from our work

- The licence forbids copying, modifying, redistributing, hosting for third parties, or using Horus to build a competing product. Access to the source grants no rights.
- Customers, pilots, testers and contributors all sign an agreement with confidentiality clauses. The NDA flagged at the green light becomes a normal part of the model, not an exception.
- Technical measures back this up (see "Technical protection to add").

### 3. Legal: no dependency forces us to open anything

The inventory covers 1,463 third-party components as of 26/09/2026 (`docs/eip/dependency-licence-inventory.xlsx`).

| Category | Count | Effect on our code |
|---|---|---|
| Permissive (MIT, BSD, Apache-2.0, ISC, Zlib, Unicode…) | 1,403 | None. We must keep their notices. |
| Weak copyleft (LGPL, MPL-2.0) | 39 | None when used unmodified. Examples: psycopg2, libvips via sharp, certifi, tqdm, 5 Rust crates. |
| Strong copyleft (GPL, AGPL) | 4 | None. Loki, Tempo, poppler and GCC run as **separate, unmodified programs**. That is aggregation, so our code is not affected. We add their licence text and a source link. **The only blocker found, PyMuPDF (AGPL, installed but never imported), was removed from the knowledge-store requirements on 26/09/2026.** |
| Source-available (RSALv2 / SSPL) | 2 | The Redis 7.4 image allows use inside Horus, but we plan to switch to Valkey (BSD) to avoid legal friction with customers. RedisInsight is kept out of customer builds. Done on 07/10/2026: Valkey 9.1.2 replaced Redis (`9b72084`), and RedisInsight starts only with the Compose profile `dev-tools`, which the installer never uses (`01df0ee`). |
| NVIDIA proprietary (CUDA wheels) | 15 | Follow NVIDIA's terms. Check redistribution before the AI-box offer. |
| AI models (Qwen, BGE, MiniLM, spaCy, T5, DistilBART) | 10 | All Apache-2.0 or MIT. Commercial use is allowed. |

**Conclusion: Horus can be 100% closed.** The only thing we "must" publish is **other people's licence texts and source locations** (a THIRD_PARTY_NOTICES file). None of our own code has to be published.

### 4. Team: three people cannot run an open-source community

A public project means reviewing public issues and PRs, running security disclosure, and keeping public docs in sync. That is a part-time job we cannot staff while building the product.

### Can all of it be closed, or does something have to be open?

- **Legally: everything can be closed.** See point 3 above.
- **For the school:** the objective asks us to *decide and justify* open or closed. Partial opening was offered as an option, not imposed. The Tek5 brief (meeting of 18/09/2026) does ask to justify the choice "even if it is only a part of it that is open source". So **a fully closed choice is allowed, but the study supervisor must validate it**; this ADR is the document sent for that validation.
- **Fallback, only if the supervisor requires something public:** the cheapest option that keeps the product closed is a separate public repository containing **no Horus code**. For example: the fictional demo corpus, the `check-docstring-length.py` pre-commit hook, or documentation templates, under MIT or CC-BY. This is not decided; it only exists in case it's needed.

---

## Alternatives considered

| Option | Why it could fit | Why rejected |
|---|---|---|
| **Permissive open source (MIT / Apache-2.0)** | Maximum adoption and contributions | Anyone, including competitors, can take, rebrand and sell Horus. Customers can self-host for free, so there's no revenue. |
| **Copyleft (GPL / AGPL), possibly with a paid dual licence** | Competitors would have to publish their changes | Customers **self-host internally**, and AGPL does not make an internal user pay, only share modifications. Many enterprise legal policies ban AGPL outright, which hurts sales. Dual licensing also needs a CLA from every contributor anyway. |
| **Open core: agent process open, MAS closed** (the mentor's example) | Satisfies "some open source" and could attract contributors | The agent service contains the RAG pipeline and tool registry (protection-plan asset #2), the part that produces the answers. The open part is useless without the closed MAS, so no real community would form, yet it hands competitors a base to fork. It also costs us public maintenance. Kept as a future option, with the triggers already written in `diffusion-strategy.md`. |
| **Business Source License 1.1** | Code visible, production use restricted | The code becomes open source automatically after at most 4 years. Everyone can read and copy the ideas today. |
| **Elastic License 2.0 / SSPL** | Blocks cloud providers from reselling | Designed against SaaS resellers. Elastic 2.0 still lets any company **self-host for free**, which is our whole market. SSPL is not even aimed at our case. |
| **PolyForm Noncommercial / Shield** | Standard texts, source visible | Shield lets customers use Horus for free as long as they don't compete with us. Noncommercial keeps commercial use paid, but all our customers are commercial, so publishing the code brings nothing and exposes it. |
| **Keep the previous LICENSE (v1) unchanged** | Already in the repo | Gaps listed below: EU-mandatory rights not respected, no third-party clause, no evaluation or contribution terms, no notice that the source itself is confidential. |

---

## Changes from the previous LICENSE (v1)

The new text is in `LICENSE` (v2, 30/09/2026).

1. **Explicit coverage.** It applies to the source code, compiled code, container images, installer, desktop app, configuration and documentation. Holding the source grants no rights.
2. **Three kinds of written agreement:** commercial, evaluation or contributor. Each has its own scope.
3. **EU-mandatory rights.** The current text bans all reverse engineering. In the EU, a contract **cannot** remove the right to make a backup copy, to observe or test the program, or to decompile it for interoperability (Directive 2009/24/EC, Art. 5(2), 5(3) and 6; Art. 8 makes such clauses null and void). v2 says "except where applicable law expressly allows it", so the rest of the clause stays enforceable.
4. **Third-party components** stay under their own licences, listed in THIRD_PARTY_NOTICES. Our licence doesn't restrict them. This is required by the Apache, MPL, LGPL, GPL and AGPL licences we use.
5. **Confidentiality** of the software, **no competing product**, and **no hosting for third parties**.
6. **Contributions** are only accepted under a signed Contributor Agreement.
7. **Customer data** remains the customer's.
8. **Licence keys.** A new clause says Horus needs a licence key, that the key stops working when the licensed period ends, and what happens then (see next section). Writing this into the licence and the contract is what makes the mechanism lawful.

---

## Licence key with time-limited access (under consideration)

**Status:** idea agreed on by the team (24/09/2026). Design and legal points below; to be confirmed before implementation.

### The idea

Horus only runs with a **licence key**. The key says who the customer is, what they paid for, and **until when**. MAS reads the key; while it is valid, Horus works. When the licensed period is over, Horus stops being usable until a new key is installed.

This fits the business model exactly:

- **Commercial key:** valid for the paid quarter, with the user cap of the tier (Starter 25, Team 100, Enterprise unlimited).
- **Evaluation key:** 90 days (one pilot quarter), no production use.
- **AI box:** the key comes pre-installed and lasts as long as the rental contract.

### How the key works (proposed design)

1. **A signed file, not a password.** The key is a small file (e.g. JSON) containing:
   - customer and site ID
   - tier and user cap
   - start date, end date and grace period
   - enabled features (e.g. marketplace later)
   - a key ID

   We sign it with a **private key only we hold** (e.g. Ed25519). Horus contains only the matching **public key**, so it can check that a key is genuine but nobody can create or edit one. Changing a single character (like the end date) breaks the signature.
2. **Checked offline.** MAS verifies the signature and dates at startup and then regularly (e.g. every hour). No internet connection and no "phone home" are needed, so the pitch promise *"works with the internet cable unplugged"* still holds.
3. **Renewal = a new key file.** An admin uploads it on an admin page (or drops it in a folder). It takes effect at once, with no reinstall and no data migration.
4. **Warnings before expiry.** Banner and admin notification at 30, 14, 7 and 1 days before the end date.
5. **Grace period.** After the end date, Horus keeps working for a grace period stated in the contract (e.g. 15–30 days, which fits quarterly billing and payment delays). Then it switches to restricted mode.
6. **Restricted mode, never destruction.** When the key has expired:
   - chat, uploads, agents and tasks stop
   - admins can still log in, **export their documents and conversations**, and enter a new key
   - **nothing is deleted, encrypted or hidden**
7. **User cap.** MAS refuses to create accounts above the cap in the key.
8. **Clock tampering.** Offline, a customer could set the server clock back. MAS stores the latest date it has seen and refuses to run if the clock goes backwards by more than a tolerance (e.g. 48 h). Offline, this can never be perfect, so the **contract and the audit clause stay the real backstop**. The key only makes misuse deliberate and provable.
9. **Our signing key is the crown jewel.** Keep it offline (not in the repo, not in CI), with a backup held by two of us. If it leaks, anyone can make keys; plan how to rotate it (Horus can trust a list of public keys).

### Is it legal?

**Yes.** Time-limited licence keys are common and lawful for B2B software in the EU (France and Spain included). They are lawful because the customer agreed to them. Certain conditions keep the key a licence-enforcement tool rather than an abusive lock:

1. **It must be in the contract before signature.** The Commercial Licence Agreement and the LICENSE must state:
   - that a key is required
   - that it is valid for the paid period
   - what happens at expiry (warnings, grace period, restricted mode)

   French law requires a seller to give information that is decisive for the buyer before the contract (Code civil art. 1112-1), and contracts must be performed in good faith (art. 1104). French courts have generally accepted software locks the customer was told about, and sanctioned vendors who used hidden locks to pressure customers.
2. **It must match what was paid for.** The key may never stop Horus *during* a period the customer has paid for. There must be no hidden remote "kill switch" (our design has none: it is offline and date-based).

   Blocking a customer's system **without a right to do so** can even be a criminal offence:
   - France: Code pénal art. 323-2, hindering the operation of an information system
   - Spain: Código Penal art. 264 bis
   - EU: Directive 2013/40/EU art. 4

   A disclosed, contractual expiry is a right; a surprise shutdown is not.
3. **Never hold the customer's data hostage.** Their documents belong to them. They are also the data controller under GDPR and must keep access to personal data (e.g. to answer access or erasure requests, and to "restore the availability and access to personal data", GDPR art. 32(1)(c)). This is why expiry leads to **restricted mode with export**, never deletion or encryption.
4. **Stay proportionate.** Advance warnings, a grace period, and reactivation as soon as the renewal is paid. In France, a non-negotiable clause that creates a "significant imbalance" in a standard-form contract can be struck out (Code civil art. 1171). Instant, silent shutdown on the first day of a late payment would be exposed to that risk.
5. **Say what happens at the end of the relationship.** If the customer does not renew, the contract should give them a reasonable window (e.g. 30 days) in restricted mode to export their data.
6. **EU-mandatory rights still apply.** The key does not prevent backup copies, study of the program, or interoperability decompilation (Directive 2009/24/EC art. 5 and 6). It only controls *use* of the software, which the licence is allowed to limit.

**Bonus: the law protects the key.** Distributing or commercially holding tools whose sole purpose is to remove or bypass a technical device protecting a computer program is prohibited (Directive 2009/24/EC art. 7(1)(c)). Bypassing the key is also a breach of the licence. So a customer who cracks the key is in breach, and anyone selling a crack is acting unlawfully.

> Have a lawyer check the exact wording of the key, expiry and grace-period clauses in the Commercial Licence Agreement before the first paid contract.

---

## Consequences

### For customers (users)

- They get a **licence, not ownership**: per site, for the subscription term, for internal use, with updates and support.
- They may not copy, redistribute, modify, host for others, or build a competing product. EU-mandatory rights still apply.
- Their documents and data stay theirs and on their premises. That is the product promise and is written into the agreement.
- They receive a THIRD_PARTY_NOTICES file listing the open-source components and their licences.

### For contributors, and the Tek5 "2 external contributions" objective

- External contributions are still possible, **by invitation**: the person signs the NDA plus the Contributor Agreement, then gets access to the private repo.
  - Check whether the EpitechPromo2027 organisation allows outside collaborators. If not, use a private mirror the team controls.
- Contributors are credited in a CONTRIBUTORS file, which also feeds the "who made what" document. The rights to their contribution are assigned to the Horus owners, so the product stays sellable.
- **Outreach changes shape.** The 8–10 spaces and 5 calls become calls to join a **closed contributor or beta programme**, not "fork our repo".
  - This adds friction (an NDA before any work). Mitigations: a one-page agreement, small scoped tasks (the 3 easy GitHub issues), and public credit.
  - **This is the main risk to present to the supervisor.**

### For the team

- **Co-ownership.** The copyright currently belongs jointly to the three of us. Generally, co-authors must agree together to exploit a joint work, so a departure or disagreement could block sales.
  - Sign a **founders' agreement** now covering ownership, decisions, and what happens if someone leaves.
  - **Assign the rights to the company** once it is created.
  - This is also the mentor's "rights assignment contracts so the project survives independently of each member".
- **Check Epitech's EIP rules** for any clause about the IP of student projects.
- We take on the **license-compliance work**: THIRD_PARTY_NOTICES, keeping copyleft components unmodified and separate, and a licence check in CI. The first and the last are in place since 07/10/2026 (`2df368e`, `ade67e9`).

### Risks we accept

- Fewer spontaneous external contributions. This is mitigated by the invited contributor programme.
- The supervisor may refuse a fully closed scope. The fallback is above.
- A licence only protects us if we can enforce it. The contracts, NDAs, OpenTimestamps proofs and technical measures support enforcement.

### Technical protection to add

Every customer receives a copy, so these measures matter.

1. **Stop shipping source code in the customer bundle.** The beta ZIP currently contains *"the source the stack builds from"* (ATP v7, Info & Access). Ship **prebuilt, signed container images** instead: from a private registry, or as image tarballs for offline sites.
2. **Licence key:** a signed, time-limited licence file (site, tier, user cap, expiry) that MAS verifies **offline**. At expiry, after warnings and a grace period, Horus switches to restricted mode with data export. See "Licence key with time-limited access" above for the design and the legal conditions.
3. **Optional hardening:** compile the core Python modules (e.g. Cython or Nuitka) for the MAS routing and document pipeline. This raises the bar; it is not a guarantee.
4. **Keep what already works:** the private repo, branch protection, and an **OpenTimestamps proof for each release** (done for the MVP), which proves authorship and date.

---

## References

- Pitch deck: `docs/eip_pool_tek5/Horus_Pitch_Demo.pptx` (slides 1, 3, 5, 6, 7, 9)
- Mentor follow-up, 19/09/2026: Objective 1, actions 1–3
- `docs/eip/dependency-licence-inventory.xlsx`
- `LICENSE`, `docs/eip/protection-plan.md`, `docs/eip/diffusion-strategy.md`, `docs/ip_protection/`
- Directive 2009/24/EC on the legal protection of computer programs, Art. 5, 6, 7(1)(c) and 8: https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32009L0024
- Licence-key legality:
  - French Code civil art. 1104 (good faith), 1112-1 (pre-contract information) and 1171 (significant imbalance in standard-form contracts)
  - French Code pénal art. 323-2
  - Spanish Código Penal art. 264 bis
  - Directive 2013/40/EU art. 4
  - GDPR art. 32(1)(c)
- Redis licences by version: https://redis.io/legal/licenses/
- Grafana Loki licensing: https://github.com/grafana/loki/blob/main/LICENSING.md
- Grafana Tempo licence: https://github.com/grafana/tempo/blob/main/LICENSE
- PyMuPDF licensing (AGPL or commercial): https://pymupdf.readthedocs.io/en/latest/about.html
- RedisInsight licence (SSPL): https://github.com/redis/RedisInsight/blob/main/LICENSE
- Model cards: Qwen/Qwen2.5-1.5B-Instruct, Qwen/Qwen3-4B-Instruct-2507, BAAI/bge-base-en-v1.5, sentence-transformers/all-MiniLM-L6-v2, spacy/en_core_web_trf, google-t5/t5-small, sshleifer/distilbart-cnn-6-6, sshleifer/distilbart-cnn-12-6 (huggingface.co)
