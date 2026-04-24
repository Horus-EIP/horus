# HORUS LIVE DEMO — 20 MIN SCRIPT

**Scenario:** Alice Chen, IT Director at FinCorp, deploys Horus to give her team a private, self-hosted AI assistant that can reason over confidential FinCorp documents.

**Before the demo starts — checklist (do this 15 min early):**

1. Open a terminal in the project root.
2. Make sure Docker Desktop is running.
3. Pre-pull images: `docker compose pull` (saves 2-3 min on stage).
4. Open these browser tabs, in order:
   - Terminal (visible, large font)
   - http://localhost:3000 (web client — not yet up)
   - http://localhost:3301 (Grafana)
   - http://localhost:16686 (Jaeger, optional)
5. Open `COPY_PASTE_CHEATSHEET.md` on a second monitor / phone.
6. Have the `demo_assets/` folder open in a file explorer, ready to drag documents.
7. Have the backup pre-recorded video queued up, just in case.

---

## 0:00 — 2:00 — STEP 1: DEPLOY PLATFORM

**What you say:**
> "Alice Chen is the IT Director at FinCorp. Her leadership just asked her to roll out AI for the whole team — but under one condition: no data leaves the company's infrastructure. That rules out every public SaaS. So today, Alice is deploying Horus, our self-hosted multi-agent orchestration system. One command."

**What you do:**

```bash
docker compose up -d
```

Then, while containers start:

```bash
docker compose ps
```

**What to point out on screen:**
- MAS orchestrator (FastAPI)
- Agent service (RAG pipeline)
- PostgreSQL, Redis, RabbitMQ, ChromaDB
- Prometheus + Grafana + Jaeger for observability
- Next.js web client

> "Eight services, one network, fully self-hosted. In 90 seconds, Alice has her private AI platform running on her own infrastructure."

Open http://localhost:3000 — landing page appears.

---

## 2:00 — 4:00 — STEP 2: CREATE ACCOUNT

**What you say:**
> "First thing Alice needs is her admin account. Because the first user registered is automatically the system administrator."

**What you do:**
1. Click **Sign Up**.
2. Use these credentials (copy from cheat sheet):
   - Username: `alice.chen`
   - Password: `FinCorp2026!`
   - Email: `alice.chen@fincorp.com`
3. Log in.
4. Land on the dashboard — briefly show the analytics graph widget (empty for now).

> "She's in. The platform issued a JWT token — all API calls are authenticated from here on."

---

## 4:00 — 6:00 — STEP 3: CREATE AI AGENT

**What you say:**
> "Now Alice wants a specialized agent for her finance team. Not a generic chatbot — one with specific skills it can be routed work for."

**What you do:**
1. Navigate to **Admin Panel → Agents → Register New Agent**.
2. Fill in (copy from cheat sheet):
   - **Name:** `FinCorp-Analyst`
   - **Description:** `Financial analyst agent for FinCorp — reasons over internal financial reports, compliance docs, and company policy.`
   - **Skills:** `financial_analysis, compliance, reporting, document_qa`
   - **Model:** default
3. Click **Register Agent**.
4. Copy the generated **API key** and show it briefly.

> "The system just minted an API key and registered the agent. It's now in the agent registry, visible to everyone, and eligible to receive tasks."

5. Go back to the dashboard — show the agent listed with status `online`.

---

## 6:00 — 8:00 — STEP 4: UPLOAD DOCUMENTS

**What you say:**
> "An agent with no knowledge is just a chatbot. Let's give it FinCorp's actual documents — confidential materials that would never leave the company."

**What you do:**
1. Go to **Knowledge Store → Upload**.
2. Drag these 5 files from `demo_assets/`:
   - `1_Q4_2025_Financial_Report.md`
   - `2_Employee_Handbook.md`
   - `3_Compliance_Guidelines.md`
   - `4_Expense_Policy.md`
   - `5_IT_Security_Policy.md`
3. Wait ~10-15 seconds for processing.

**What to point out:**
- Each document gets an auto-detected **category** (Finance, HR, Compliance, etc.).
- **Entities extracted**: people names (John Smith, Sarah Johnson), amounts ($4.2M, €500K), dates (Q4 2025, Jan 2026).
- A short auto-generated **summary** per doc.

> "No manual tagging. The pipeline analyzed every document, categorized it, pulled out entities, and indexed it into ChromaDB — all in under 20 seconds per file."

---

## 8:00 — 10:00 — STEP 5: CHAT WITH AGENT

**What you say:**
> "Now the fun part. Alice asks the agent real questions, and the agent reasons over FinCorp's documents to answer — with source citations."

**What you do:**
1. Go to **Conversations → New Conversation**.
2. Name it: `FinCorp Finance Review`
3. Paste the **first prompt** from the cheat sheet:

> **Prompt 1 (simple):**
> `What was FinCorp's Q4 2025 revenue and who signed the report?`

Expected response: cites Q4 report, mentions $4.2M revenue and John Smith (CFO), with source citation.

4. Then paste the **complex prompt**:

> **Prompt 2 (multi-step reasoning):**
> `Cross-reference our expense policy with the Q4 report — are there any reimbursement categories where we spent more than the policy allows, and who would be the approver for an overage?`

Expected: multi-step reasoning, cites both documents, identifies approver (Sarah Johnson or named approver in expense policy).

> "Notice the citations at the bottom. Every claim is grounded in a FinCorp document. No hallucinations about company data."

---

## 10:00 — 13:00 — STEP 6: QUERY KNOWLEDGE

**What you say:**
> "Sometimes you don't want a chat — you want to search. The knowledge store has smart filters."

**What you do:**
1. Go to **Knowledge Store → Smart Search**.
2. Query: `password policy` — show result from IT Security doc, with excerpt highlighting.
3. Apply filter **Category = Compliance**, then search `GDPR` — narrow to compliance doc.
4. Apply filter **Entity = person: Michael Brown** — show all docs mentioning the Compliance Officer.
5. Apply filter **Entity = amount** — show docs with financial figures.

> "Category, entity, topic filters — under 3 seconds per query."

---

## 13:00 — 16:00 — STEP 7: ADMIN DASHBOARD

**What you say:**
> "Alice now needs to onboard her team. Admin panel."

**What you do:**
1. Go to **Admin Panel → Users → Create User**.
2. Create these three users (copy from cheat sheet):

| Username | Password | Role |
|----------|----------|------|
| bob.martinez | Manager2026! | manager |
| carol.white | User2026! | user |
| david.kim | User2026! | user |

3. Show the user list — 4 users including Alice.
4. Demonstrate **role change**: promote `carol.white` → `manager`, then back to `user`.
5. Demonstrate **delete**: create throwaway `test.user` / `Test2026!`, then delete them.

> "Full user lifecycle. Role changes are immediate — the next request from that user reflects the new permissions."

---

## 16:00 — 18:00 — STEP 8: MONITORING

**What you say:**
> "Running in production means knowing what's happening. Horus ships with full observability."

**What you do:**
1. Switch to the Grafana tab (http://localhost:3301 — login `admin` / `admin`).
2. Open the **Horus Overview** dashboard.
3. Point out the panels:
   - Active agents
   - Running / pending / completed tasks
   - Request latency (p50, p95, p99)
   - RabbitMQ queue depth
   - Per-agent response time
4. Flip to Jaeger (if time) and show one distributed trace end-to-end: Web Client → MAS → RabbitMQ → Agent → Response.

> "Every request is traced. Any failure, we see it. Any slow agent, we see it."

---

## 18:00 — 20:00 — STEP 9: STRESS TEST

**What you say:**
> "Last thing — Alice wants to be sure this will hold up under real team load. Let's fire 10 tasks at once."

**What you do:**
1. Go to **Tasks → Bulk Create** (or run the stress script below in the terminal):

```bash
bash demo_assets/stress_test.sh
```

2. Flip to **Tasks** page — show queue: 10 pending → running → completed.
3. Flip back to Grafana — the `Running Tasks` line spikes, then drains.
4. Show WebSocket notifications firing on the dashboard as tasks complete.
5. Cancel one pending task live (F20) to prove cancellation works.

> "Ten concurrent tasks, routed by skill, tracked in real time, with live WebSocket updates. All on Alice's own infrastructure. That's Horus."

---

## WHAT TO SAY IF SOMETHING BREAKS

- **Docker slow to start:** "While the containers finish initializing, let me walk you through the architecture..." — then show the architecture diagram.
- **Upload fails:** retry once; if it still fails, say "I'll switch to the pre-recorded version of this segment" and cut to backup video.
- **Agent doesn't respond:** check RabbitMQ queue in Grafana — the visible queue depth actually *demonstrates* the messaging layer works, use it.
- **Anything catastrophic:** "Demos are demos — let me switch to the pre-recorded walkthrough" and play backup video.

## AFTER THE DEMO

Be ready for these questions:
- **"How does this compare to ChatGPT Enterprise?"** — Self-hosted, no data leaves; multi-agent with skill routing; audit trail via Jaeger.
- **"Can I plug in my own LLM?"** — Yes, the Agent Service is model-agnostic.
- **"What about scaling?"** — Horizontal scale the Agent Service; RabbitMQ handles backpressure.
- **"Pricing?"** — Deflect: "Happy to follow up with commercial terms separately."
