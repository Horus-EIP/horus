# Demo

Everything for a 20-minute live demo: the script, copy-paste commands for the live terminal, and the post-demo action plan.

---

## HORUS LIVE DEMO — 20 MIN SCRIPT

**Scenario:** Alice Chen, IT Director at FinCorp, deploys Horus to give her team a private, self-hosted AI assistant that can reason over confidential FinCorp documents.

**Before the demo starts — checklist (do this 15 min early):**

1. Open a terminal in the project root.
2. Make sure Docker Desktop is running.
3. Set the admin account you will demo with, **before the first `up`**. In
   `src/infra/.env` set `SUPER_USER_USERNAME=alice.chen` and
   `SUPER_USER_PASSWORD=FinCorp2026!`. MAS seeds this account at startup
   (`src/services/mas/db/init_setup.py`) and only creates it when it does not
   already exist, so setting it after the first `up` has no effect.
4. Pre-pull images: `docker compose pull` (saves 2-3 min on stage).
5. Warm the model caches: bring the stack up once and wait for `vllm` to report
   healthy (`docker compose ps`). The AWQ weights download into the `vllm_hf_cache`
   volume on first start — several GB, and the healthcheck allows 300 s for it. Skip
   this and the "90 seconds" in Step 1 will not survive contact with the stage.
6. Open these browser tabs, in order:
   - Terminal (visible, large font)
   - http://localhost:3000 (web client — not yet up)
   - http://localhost:3000/admin/traces (in-app traces page — backed by Tempo; same login as the web client, admin role)
7. Open `copy-paste-cheatsheet.md` (same folder) on a second monitor / phone.
8. Have the `demo_assets/` folder open in a file explorer, ready to drag documents.
9. Have the backup pre-recorded video queued up, just in case.

---

### 0:00 — 2:00 — STEP 1: DEPLOY PLATFORM

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
- vLLM serving the 4B AWQ worker model
- PostgreSQL, Redis, RabbitMQ, ChromaDB
- Prometheus + Loki + Tempo for observability (surfaced through the web client's in-app admin pages)
- Next.js web client

> "Twelve services, one network, fully self-hosted. In 90 seconds, Alice has her private AI platform running on her own infrastructure."

Open http://localhost:3000 — landing page appears.

---

### 2:00 — 4:00 — STEP 2: SIGN IN AS ADMIN

**What you say:**
> "First thing Alice needs is her admin account. Horus provisions that account at startup from the deployment's own environment file — there is no 'first user to register wins' shortcut, because that is a race anyone who can reach the box could win."

**What you do:**
1. Click **Sign in**.
2. Use these credentials (copy from cheat sheet):
   - Username: `alice.chen`
   - Password: `FinCorp2026!`
3. Land on the dashboard — briefly show the analytics graph widget (empty for now).

> "She's in, with the `admin` role. The platform issued a JWT token — all API calls are authenticated from here on."

**Presenter note:** these are the values you put in `SUPER_USER_USERNAME` /
`SUPER_USER_PASSWORD` during the pre-demo checklist. Do **not** use **Sign up** here:
registration always creates a plain `user` (the role column defaults to `user` and
`POST /auth/register` never sets it), so the admin panel stays hidden and Step 3 fails.

---

### 4:00 — 6:00 — STEP 3: CREATE AI AGENT

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

### 6:00 — 8:00 — STEP 4: UPLOAD DOCUMENTS

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

### 8:00 — 10:00 — STEP 5: CHAT WITH AGENT

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

### 10:00 — 13:00 — STEP 6: QUERY KNOWLEDGE

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

### 13:00 — 16:00 — STEP 7: ADMIN DASHBOARD

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

### 16:00 — 18:00 — STEP 8: MONITORING

**What you say:**
> "Running in production means knowing what's happening. Horus ships with full observability."

**What you do:**
1. As Alice (admin role, already logged in), open the **Metrics** page at http://localhost:3000/admin/metrics — no separate login.
2. Point out the panels (the in-app "MAS Overview"):
   - Task Queue Depth
   - Task Errors Rate
   - Active Agents
3. Open the **Logs** page at http://localhost:3000/admin/logs — live tail across services, backed by Loki.
4. Open the **Traces** page at http://localhost:3000/admin/traces — search for a trace, then show one distributed trace end-to-end in the span waterfall: Web Client → MAS → RabbitMQ → Agent → Response.

> "Every request is traced. Any failure, we see it. Any slow agent, we see it — all inside the app, no second tool to log into."

---

### 18:00 — 20:00 — STEP 9: STRESS TEST

**What you say:**
> "Last thing — Alice wants to be sure this will hold up under real team load. Let's fire 10 tasks at once."

**What you do:**
1. Go to **Tasks → Bulk Create** (or run the stress script below in the terminal):

```bash
bash demo_assets/stress_test.sh
```

2. Flip to **Tasks** page — show queue: 10 pending → running → completed.
3. Flip to the **Metrics** page (/admin/metrics) — the `Task Queue Depth` panel spikes, then drains.
4. Show WebSocket notifications firing on the dashboard as tasks complete.
5. Cancel one pending task live (F20) to prove cancellation works.

> "Ten concurrent tasks, routed by skill, tracked in real time, with live WebSocket updates. All on Alice's own infrastructure. That's Horus."

---

### WHAT TO SAY IF SOMETHING BREAKS

- **Docker slow to start:** "While the containers finish initializing, let me walk you through the architecture..." — then show the architecture diagram.
- **Upload fails:** retry once; if it still fails, say "I'll switch to the pre-recorded version of this segment" and cut to backup video.
- **Agent doesn't respond:** check the queue depth on the in-app **Metrics** page (/admin/metrics) — the visible `Task Queue Depth` actually *demonstrates* the messaging layer works, use it.
- **Anything catastrophic:** "Demos are demos — let me switch to the pre-recorded walkthrough" and play backup video.

### AFTER THE DEMO

Be ready for these questions:
- **"How does this compare to ChatGPT Enterprise?"** — Self-hosted, no data leaves; multi-agent with skill routing; audit trail via OpenTelemetry traces (Tempo backend), viewable in-app at /admin/traces.
- **"Can I plug in my own LLM?"** — Yes, the Agent Service is model-agnostic.
- **"What about scaling?"** — Horizontal scale the Agent Service; RabbitMQ handles backpressure.
- **"Pricing?"** — Deflect: "Happy to follow up with commercial terms separately."

---

## COPY-PASTE CHEAT SHEET

Keep this open on a second monitor or phone during the demo. Every value is ready to paste.

---

### DEPLOY COMMANDS

```bash
docker compose pull
docker compose up -d
docker compose ps
```

Open afterwards: http://localhost:3000

---

### ADMIN ACCOUNT (Alice)

Set these in `src/infra/.env` before the first `docker compose up` — MAS seeds the
account on startup. The sign-up form takes a username and password only; there is no
email field.

| Field | Value |
|-------|-------|
| Username | `alice.chen` |
| Password | `FinCorp2026!` |
| Seeded from | `SUPER_USER_USERNAME` / `SUPER_USER_PASSWORD` in `src/infra/.env` |

---

### AGENT REGISTRATION

| Field | Value |
|-------|-------|
| Name | `FinCorp-Analyst` |
| Description | `Financial analyst agent for FinCorp — reasons over internal financial reports, compliance docs, and company policy.` |
| Skills | `financial_analysis, compliance, reporting, document_qa` |
| Model | (leave default) |

---

### DOCUMENTS TO UPLOAD

All in `demo_assets/`, upload in this order:

1. `1_Q4_2025_Financial_Report.md`
2. `2_Employee_Handbook.md`
3. `3_Compliance_Guidelines.md`
4. `4_Expense_Policy.md`
5. `5_IT_Security_Policy.md`

---

### CHAT PROMPTS

**Conversation name:** `FinCorp Finance Review`

**Prompt 1 — simple retrieval (expect < 15s):**

```
What was FinCorp's Q4 2025 revenue and who signed the report?
```

**Prompt 2 — multi-step reasoning (expect < 60s):**

```
Cross-reference our expense policy with the Q4 report — are there any reimbursement categories where we spent more than the policy allows, and who would be the approver for an overage?
```

**Prompt 3 — backup if time allows:**

```
Summarize FinCorp's GDPR obligations from the compliance document and list any deadlines we have in the next 90 days.
```

---

### KNOWLEDGE STORE QUERIES

| # | Query | Filter |
|---|-------|--------|
| 1 | `password policy` | none |
| 2 | `GDPR` | Category = Compliance |
| 3 | (empty search) | Entity = person: Michael Brown |
| 4 | `reimbursement` | Entity type = amount |
| 5 | `incident response` | Category = Security |

---

### USERS TO CREATE (Admin Panel)

| Username | Password | Role |
|----------|----------|------|
| bob.martinez | Manager2026! | manager |
| carol.white | User2026! | user |
| david.kim | User2026! | user |
| test.user | Test2026! | user *(create then delete on stage)* |

**Role change demo:** `carol.white` → `manager` → back to `user`.

---

### STRESS TEST TASKS (if running manually instead of script)

Paste these one per task, all with skill `financial_analysis`:

1. `Summarize the key financial risks from the Q4 2025 report.`
2. `List all reimbursable expense categories over $500.`
3. `What is our SOX compliance audit schedule?`
4. `Who is the designated Data Protection Officer?`
5. `What are the maximum vacation days per year?`
6. `Explain our incident response SLA.`
7. `What is the minimum password length required?`
8. `Summarize Q4 2025 operating expenses.`
9. `Who approves expense reports over $5,000?`
10. `What is the notice period for terminating an employee?`

---

### USEFUL URLS

| Service | URL | Credentials |
|---------|-----|-------------|
| Web client | http://localhost:3000 | alice.chen / FinCorp2026! |
| Metrics (in-app) | http://localhost:3000/admin/metrics | alice.chen / FinCorp2026! (admin role) |
| Logs (in-app) | http://localhost:3000/admin/logs | alice.chen / FinCorp2026! (admin role) |
| Traces (in-app) | http://localhost:3000/admin/traces | alice.chen / FinCorp2026! (admin role) |
| RabbitMQ | http://localhost:15672 | guest / guest |

> Prometheus, Loki, and Tempo run as internal-only backends inside the Docker network (not published to the host) — view them through the in-app admin pages above.

---

### RESET EVERYTHING (if demo breaks mid-run)

```bash
docker compose down -v
docker compose up -d
```

~2 minutes to come back up clean.

---

## Post-Demo Action Plan — Horus

Based on mock-presentation feedback (2026-04-24) and a code audit against the beta feature list F1–F24. Each item is marked with current status, the file(s) involved, and a concrete next step.

---

### 1. Feedback Summary (what reviewers said)

1. **Agents must visibly show they work and which skill they used.** Today a user sees the response but not which agent produced it or which skill was invoked.
2. **Chat is not the same as a task.** Right now users type in chat and the backend silently creates a task. We need an explicit, separate task-creation flow.
3. **Task creation needs three modes:**
   - Pick a skill from a list.
   - Pick a specific agent from the registry.
   - "Auto" — system picks any available agent that has the requested skill, or waits for a chosen agent to become free.
4. **Docker startup must ship with ≥ 5 default agents pre-registered.** A fresh install should not require the admin to manually add agents before anything works.
5. **Conversation creation must use a custom name.** This already works in the API but the UI doesn't surface it.
6. **A real analytics page with a live graph** — active agents, running tasks, pending tasks, updating in real time.
7. **Every feature F1–F24 must verifiably exist.**

---

### 2. Feature Verification Matrix (F1–F24)

Legend: ✅ works end-to-end · 🟡 backend OK, UI missing or incomplete · ❌ missing · 🔎 needs manual retest on fixed build

| ID | Feature | Status | File(s) | Required action |
|----|---------|--------|---------|-----------------|
| F1 | Log in (JWT) | ✅ | `src/services/mas/auth/routes.py` | Retest after agent-service rebuild. |
| F2 | Admin create user | ✅ | `src/services/mas/users/routes.py` | Retest. |
| F3 | Admin delete user | ✅ | `src/services/mas/users/routes.py` | Retest. |
| F4 | Assign role | ✅ | `src/services/mas/users/routes.py` | Retest. |
| F5 | View all users | ✅ | `src/services/mas/users/routes.py` | Retest. |
| F6 | Create conversation with custom name | 🟡 | `src/services/mas/conversations/routes.py:43-54`, `src/services/web-client/lib/chat/api.ts:54-73` | API accepts `name`; UI falls back to a timestamp. **Add a "Name your conversation" modal on the Conversations page.** |
| F7 | List conversations | ✅ | `src/services/mas/conversations/routes.py` | Retest. |
| F8 | Delete conversation (owner/admin/manager) | ✅ | `src/services/mas/conversations/routes.py` | Retest. |
| F9 | Upload document + auto-analysis | 🔎 | `src/services/agent/app/ai_agents/knowledge_store_client.py` | Retest after the regex + merge-conflict fixes. |
| F10 | List documents | ✅ | Knowledge Store service | Retest. |
| F11 | Delete document | ✅ | Knowledge Store service | Retest. |
| F12 | Query documents with filters | ✅ | Knowledge Store service | Retest smart-search filters (category, entity, topic). |
| F13 | Register agent with API key | ✅ | `src/services/mas/agents/routes.py:44-108` | Retest. |
| F14 | View registered agents | ✅ | `src/services/web-client/app/(protected)/admin/agents/page.tsx` | Retest. |
| F15 | Send message | 🟡 | `src/services/mas/chat/routes.py` | Works but **must display which agent and which skill handled the reply** (see §3.1). |
| F16 | Receive AI response w/ citations | 🔎 | `src/services/agent/app/ai_agents/rag_pipeline.py` | Retest after agent service rebuild. |
| F17 | Message history | ✅ | `src/services/mas/conversations/routes.py` | Retest. |
| F18 | Create task with skills + agent selection | ❌ | `src/services/mas/tasks/routes.py:192-308`, `schemas.py:25-30` | Backend accepts `skills_required` but has **no `agent_id` field and no "auto" mode**. No UI exists. **This is the biggest gap** (see §3.2). |
| F19 | Task queue stats | ✅ | `src/services/mas/tasks/routes.py:57-122` (`GET /tasks/stats/queue`) | Retest. |
| F20 | Cancel task | ✅ | `src/services/mas/tasks/routes.py:437-484` (`PATCH /tasks/task-cancel/{id}`) | Retest. |
| F21 | WebSocket task result notification | 🟡 | `src/services/mas/chat/routes.py:27-110`, `send_messages_via_websockets` in tasks routes | WebSocket loop does `receive_text()` but ignores it; actual push happens from task routes. **Add an explicit "task_complete" event type and confirm the client handles it** (see §3.3). |
| F22 | Dashboard with analytics graph | ✅ | `src/services/web-client/app/(protected)/dashboard/page.tsx:1-391` | Already renders a live canvas graph + stat cards + agent status, refreshes every 10 s. **Keep this, but it consumes `/tasks/stats/queue` — see F23.** |
| F23 | Live analytics (active agents / running / pending) | 🟡 | No `/analytics` endpoint exists; dashboard derives everything from `/tasks/stats/queue` + `/agents/details/`. | Works today by composition. **Optional: add a consolidated `GET /analytics/overview` that returns all three counts in one call, to simplify the UI** (see §3.4). |
| F24 | Delete agent (admin/manager) | ✅ | `src/services/mas/agents/routes.py:111-147` | Retest. |

**Net current state:** 17 features work ✅, 5 need UI/behaviour work 🟡, 1 is a hard miss ❌, 4 need manual retest on the fixed build.

---

### 3. Detailed Action Items

#### 3.1 Show which agent + skill handled each reply (feedback #1)

- **Backend:** when `send_result` posts a task result, include `agent_id`, `agent_name`, `skill_used` in the WebSocket payload. File: `src/services/agent/app/agent_server/server.py` (`send_result` function) and `src/services/mas/tasks/routes.py` (`/tasks/task-result/`).
- **Frontend:** render an attribution chip below each assistant message: "Answered by **FinCorp-Analyst** using skill `financial_analysis`". File: `src/services/web-client/app/(protected)/chat/` message component.
- **Estimate:** 0.5 day.

#### 3.2 Task creation flow, separate from chat (feedback #2 & #3)

- **Backend changes** in `src/services/mas/tasks/routes.py` and `schemas.py`:
  - Extend `TaskForm` schema with three optional fields: `agent_id` (UUID, optional), `skill_required` (str, optional — already exists as `skills_required`, normalize naming), `mode` (enum: `auto` | `specific_agent` | `any_with_skill`).
  - Update the task dispatcher: if `agent_id` is set → route directly to that agent's queue; if `skill_required` is set and `mode=any_with_skill` → pick first idle agent with that skill; if `mode=auto` → current LLM-driven selection.
  - Queue-on-busy behaviour: when `mode=specific_agent` and the agent is busy, do NOT fail — enqueue with `status=pending` and a `blocked_on_agent` marker. Dispatcher retries when a heartbeat or task-complete frees the agent.
- **Frontend changes** in `src/services/web-client/app/(protected)/`:
  - New page: `tasks/new/page.tsx` — form with fields:
    - Demand (textarea).
    - Skill dropdown (populated from distinct `skill` values across registered agents).
    - Mode radio: Auto / Pick an agent / Any agent with this skill.
    - Agent dropdown (only shown when "Pick an agent" selected; populated from `/agents/details/`).
  - Add a "New task" button to the Tasks page header.
- **Estimate:** 2 days (1 backend, 1 frontend).

#### 3.3 Confirm WebSocket pushes task results (feedback implicit via F16/F21)

- File: `src/services/mas/chat/routes.py:27-110`. The `while True: await websocket.receive_text()` loop currently discards inbound messages. Two things to verify:
  1. The broadcast helper `send_messages_via_websockets` (called from `tasks/routes.py` at lines 224, 278, 423) successfully finds and writes to the socket saved by `save_new_client`. Add a log line at each push.
  2. The client side handles the message type. File: `src/services/web-client/lib/chat/socket.ts` (or wherever the WS client lives). Add a switch on `message_type` and render `task_complete` events inline in the chat.
- **Estimate:** 0.5 day.

#### 3.4 Default agent seeding on docker startup (feedback #4)

- Create `src/services/mas/db/seed_agents.py` that, after migrations, registers 5 default agents if and only if the agent table is empty:

| Name | Type | Skills | Description |
|------|------|--------|-------------|
| `General-Assistant` | general | `conversation, summarization, document_qa` | Default general-purpose agent. |
| `Finance-Analyst` | analyst | `financial_analysis, reporting, calculation` | Reads financial documents, computes figures. |
| `Compliance-Officer` | researcher | `compliance, regulation, policy_lookup` | GDPR, SOX, MiCA, policy questions. |
| `Document-Writer` | writer | `drafting, summarization, editing` | Produces written outputs. |
| `Researcher` | researcher | `research, synthesis, citation` | Multi-source document research. |

- Hook: call the seed from `init_setup.py` (already seeds the admin user at lines 90-100). Pattern matches what's already there.
- Docker: no compose change needed — the init script runs in the MAS container startup.
- Each agent gets a stable API key recorded in a secret or printed once to the log. For the demo, printing to the MAS log is acceptable.
- **Estimate:** 0.5 day.

#### 3.5 Conversation custom-name modal (feedback #5)

- File: `src/services/web-client/app/(protected)/conversations/` (or wherever the "New conversation" button lives).
- Replace the silent-create-with-timestamp flow with a modal: one text input `name` (required), Create / Cancel buttons. Pass the value to the existing `createConversation(name)` API helper in `src/services/web-client/lib/chat/api.ts:54-73`.
- **Estimate:** 1-2 hours.

#### 3.6 Analytics page polish (feedback #6)

- The dashboard page already exists at `src/services/web-client/app/(protected)/dashboard/page.tsx` with a live canvas graph and 10-second refresh. Verify it renders correctly on the fixed build and add the following if absent:
  - Three numeric stat cards: Active Agents · Running Tasks · Pending Tasks.
  - Line chart over time, last 60 minutes, X-axis = time, Y-axis = count. Already present as a canvas graph; confirm it plots all three series.
  - Per-agent status table.
- **Optional backend improvement:** add `GET /analytics/overview` returning `{active_agents, running_tasks, pending_tasks, timestamp}` in one call, so the frontend doesn't need to chain `/tasks/stats/queue` + `/agents/details/`. Low priority — current composition works.
- **Estimate:** 0.5 day verification, +0.5 day if adding the consolidated endpoint.

---

### 4. Bug Fixes Still Open From Build Issues

(These came out of the 2026-04-24 session, worth keeping in a single punch list.)

- [ ] **`src/services/agent/app/agent_server/server.py` — architectural cleanup.** File currently has duplicated definitions of `Task`, `Result`, `_consume_messages`, `_consume_agent_messages`, `_format_delegation_context`, `_process_delegation_message`, `_send_delegation_result`. The imports at the top pull from submodules, but local redefinitions lower down shadow them. Functionally it works; remove lines ~94-124 and ~298-637 so only the imports + `send_result` + lifespan + routes remain.
- [ ] **`stress_test.sh` credentials.** Script uses a hard-coded JWT; move to env-only and document how to generate one.
- [ ] **Git hygiene.** Run `git diff --check` at the tip of every branch to catch stray merge-conflict markers in non-Python files (YAML, JSON, docs) before CI.

---

### 5. Recommended Order of Work

Two-week plan assuming one full-time developer, priorities from most blocking to least:

**Week 1 — unblocks the beta demo**

1. Day 1: Post-demo bug fixes — finish §4 punch list (server.py cleanup, stress_test.sh credentials).
2. Day 2: §3.4 Default agent seeding. Without this, a judge who runs `docker compose up` fresh sees an empty system.
3. Day 3-4: §3.2 Task creation flow — backend.
4. Day 5: §3.2 Task creation flow — frontend.

**Week 2 — polish and verification**

5. Day 6: §3.1 Agent + skill attribution chips.
6. Day 7 morning: §3.5 Conversation custom-name modal.
7. Day 7 afternoon: §3.3 WebSocket push verification.
8. Day 8: §3.6 Analytics page polish + optional consolidated endpoint.
9. Day 9: Full regression over F1-F24. Record a clean demo video as backup.
10. Day 10: Buffer for anything that slipped.

---

### 6. Definition of Done for the Real Presentation

Before the graded beta review, every row in the verification matrix §2 must be ✅. The demo script must walk through at least one feature per user role (admin, manager, user). Include:

- A fresh `docker compose up` from a clean checkout, producing a working system with 5 agents, and the admin user `alice.chen`, in under 3 minutes.
- A task created via the new `/tasks/new` page in all three modes (auto, specific agent, any-with-skill).
- A conversation created with the custom-name modal.
- The dashboard analytics graph showing live data during the stress-test segment.
- Every assistant reply visibly attributed to the agent and skill that produced it.

If any of the above is missing on demo day, the presentation is not ready.
