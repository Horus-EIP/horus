# Post-Demo Action Plan — Horus

Based on mock-presentation feedback (2026-04-24) and a code audit against the beta feature list F1–F24. Each item is marked with current status, the file(s) involved, and a concrete next step.

---

## 1. Feedback Summary (what reviewers said)

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

## 2. Feature Verification Matrix (F1–F24)

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

## 3. Detailed Action Items

### 3.1 Show which agent + skill handled each reply (feedback #1)

- **Backend:** when `send_result` posts a task result, include `agent_id`, `agent_name`, `skill_used` in the WebSocket payload. File: `src/services/agent/app/agent_server/server.py` (`send_result` function) and `src/services/mas/tasks/routes.py` (`/tasks/task-result/`).
- **Frontend:** render an attribution chip below each assistant message: "Answered by **FinCorp-Analyst** using skill `financial_analysis`". File: `src/services/web-client/app/(protected)/chat/` message component.
- **Estimate:** 0.5 day.

### 3.2 Task creation flow, separate from chat (feedback #2 & #3)

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

### 3.3 Confirm WebSocket pushes task results (feedback implicit via F16/F21)

- File: `src/services/mas/chat/routes.py:27-110`. The `while True: await websocket.receive_text()` loop currently discards inbound messages. Two things to verify:
  1. The broadcast helper `send_messages_via_websockets` (called from `tasks/routes.py` at lines 224, 278, 423) successfully finds and writes to the socket saved by `save_new_client`. Add a log line at each push.
  2. The client side handles the message type. File: `src/services/web-client/lib/chat/socket.ts` (or wherever the WS client lives). Add a switch on `message_type` and render `task_complete` events inline in the chat.
- **Estimate:** 0.5 day.

### 3.4 Default agent seeding on docker startup (feedback #4)

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

### 3.5 Conversation custom-name modal (feedback #5)

- File: `src/services/web-client/app/(protected)/conversations/` (or wherever the "New conversation" button lives).
- Replace the silent-create-with-timestamp flow with a modal: one text input `name` (required), Create / Cancel buttons. Pass the value to the existing `createConversation(name)` API helper in `src/services/web-client/lib/chat/api.ts:54-73`.
- **Estimate:** 1-2 hours.

### 3.6 Analytics page polish (feedback #6)

- The dashboard page already exists at `src/services/web-client/app/(protected)/dashboard/page.tsx` with a live canvas graph and 10-second refresh. Verify it renders correctly on the fixed build and add the following if absent:
  - Three numeric stat cards: Active Agents · Running Tasks · Pending Tasks.
  - Line chart over time, last 60 minutes, X-axis = time, Y-axis = count. Already present as a canvas graph; confirm it plots all three series.
  - Per-agent status table.
- **Optional backend improvement:** add `GET /analytics/overview` returning `{active_agents, running_tasks, pending_tasks, timestamp}` in one call, so the frontend doesn't need to chain `/tasks/stats/queue` + `/agents/details/`. Low priority — current composition works.
- **Estimate:** 0.5 day verification, +0.5 day if adding the consolidated endpoint.

---

## 4. Bug Fixes Still Open From Build Issues

(These came out of the 2026-04-24 session, worth keeping in a single punch list.)

- [ ] **`src/services/agent/app/agent_server/server.py` — architectural cleanup.** File currently has duplicated definitions of `Task`, `Result`, `_consume_messages`, `_consume_agent_messages`, `_format_delegation_context`, `_process_delegation_message`, `_send_delegation_result`. The imports at the top pull from submodules, but local redefinitions lower down shadow them. Functionally it works; remove lines ~94-124 and ~298-637 so only the imports + `send_result` + lifespan + routes remain.
- [ ] **Grafana datasource error on startup.** Mitigation today: `docker compose down -v` before bring-up. Root cause: stale state in the `grafana_data` volume referencing a datasource UID that no longer matches provisioning. Investigate whether we should remove the named volume from compose, or add a provisioning reset script.
- [ ] **Port consistency.** Grafana is exposed on **3301**, not 3001. Update any docs, READMEs, and demo scripts accordingly.
- [ ] **`stress_test.sh` credentials.** Script uses a hard-coded JWT; move to env-only and document how to generate one.
- [ ] **Git hygiene.** Run `git diff --check` at the tip of every branch to catch stray merge-conflict markers in non-Python files (YAML, JSON, docs) before CI.

---

## 5. Recommended Order of Work

Two-week plan assuming one full-time developer, priorities from most blocking to least:

**Week 1 — unblocks the beta demo**

1. Day 1: Post-demo bug fixes — finish §4 punch list (server.py cleanup, Grafana volume reset).
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

## 6. Definition of Done for the Real Presentation

Before the graded beta review, every row in the verification matrix §2 must be ✅. The demo script must walk through at least one feature per user role (admin, manager, user). Include:

- A fresh `docker compose up` from a clean checkout, producing a working system with 5 agents, and the admin user `alice.chen`, in under 3 minutes.
- A task created via the new `/tasks/new` page in all three modes (auto, specific agent, any-with-skill).
- A conversation created with the custom-name modal.
- The dashboard analytics graph showing live data during the stress-test segment.
- Every assistant reply visibly attributed to the agent and skill that produced it.

If any of the above is missing on demo day, the presentation is not ready.
