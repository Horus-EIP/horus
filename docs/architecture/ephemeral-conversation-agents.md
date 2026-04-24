# Per-conversation (“ephemeral”) agents — what would be needed

## Implemented in-repo (Horus-aligned pooling)

MAS and the Agent service use **shared work queues per agent type** (`{agent_work_queue_prefix}.{type}`, default `horus.work.general`). Registration still creates a unique `agent_id` per worker for heartbeats and API keys, but **task dispatch** targets the type queue so multiple containerized specialists can share load. `/tasks/task-result/` accepts any worker whose `AgentTypes` matches the task assignee, while the JSON body carries the assignee’s `agent_id`.

The rest of this note discusses **per-conversation OS processes** (true ephemeral VMs/containers per chat), which remains an **optional deployment** layer on top.

---

This note explains the gap between the **desired behavior** (create an agent when a chat needs compute, then stop or delete it when the chat ends) and designs that stop at **pooled specialists**, and what you would add for stricter isolation.

## Desired behavior (summary)

- Do **not** rely on a single worker that registers when the stack starts (or treat that only as an implementation detail).
- When a user opens a chat or sends a task, **provision** something that can run the agent pipeline.
- When the answer is done, that worker **idles, scales to zero, or stops**.
- When the **conversation is deleted**, any dedicated resources for that chat are **released** (unregister agent, delete queue, stop process).

## How messaging works now (after pooling)

1. **Registration**  
   Each worker calls `POST /agents/register` and gets its own `agent_id` and `api_key`. MAS ensures the **shared** queue for that worker’s `AgentTypes` exists (same queue name for all workers of that type).

2. **Dispatch**  
   MAS publishes task JSON to `resolve_work_queue_for_agent_id(assignee)` (e.g. `horus.work.general`), including `assigned_agent_id` for result correlation.

3. **Execution**  
   Workers consume the **type** queue (`WORK_QUEUE_NAME` in `agent_server/server.py`). Any idle pool member may run the task.

4. **Conversation delete**  
   Still cascades messages and tasks only; unregistering a worker removes its DB row but **not** the shared type queue.

## Why you cannot get true per-chat agents with a tiny change

If MAS registered a **new** `agent_id` per conversation and created a new queue:

- Something must **consume** that queue. The default Agent image listens to **one work queue per `AGENT_TYPE`**, not one queue per registered UUID.
- Spawning **one container / process per conversation** that loads the **GPU LLM** would mean **very slow** first replies and **high** memory use unless you use a remote API model or a separate lightweight worker.
- “Sleep” after one answer is either **process exit** (needs a supervisor to start again on the next message) or **scale-to-zero** (Kubernetes, Cloud Run, etc.) — **outside** this repo unless you add an orchestration layer.

In other words: **per-chat agents are a product of deployment + messaging design**, not only “call `create_agent` at chat open.”

## Practical directions (choose one)

### 1. Shared work queue + pool of stateless workers (recommended for “always on” pool)

- MAS publishes tasks to a **single** queue (e.g. `agent.work`) or an **exchange** with routing by skill, not by `agent_id` per user.
- **N** identical Agent workers all consume that queue; each task payload already carries `conversation_id` and `task_id`.
- “Ephemeral” becomes **logical**: no per-chat registry row required. Conversation delete only clears DB chat data (as today).
- **Sleep / scale**: scale the **deployment** replicas based on queue depth or schedule (infra).

**Code changes (high level):** RabbitMQ topology in MAS and Agent consumer, registration model (optional: one “pool” agent or no per-worker queue), adjust `publish()` paths in `tasks/routes.py` and related code.

### 2. One short-lived worker per task or per conversation (true isolation)

- Use **Kubernetes Job**, **AWS Batch**, **Cloud Run jobs**, or **Docker** spawned by a small **controller** service when a task is created.
- That job runs the Agent (or a slim “task runner”) **once**, posts the result to MAS, then **exits**.
- On conversation delete, cancel **pending** jobs and rely on **job TTL** for orphaned work.

**Code changes:** New “runner” entrypoint, MAS or sidecar that submits jobs, credentials and networking to reach MAS / RabbitMQ / Knowledge Store, and policy for GPU vs CPU vs remote LLM.

### 3. “Logical” per-chat agent (metadata only)

- Add a table or columns linking `conversation_id` → `agent_id` for **audit / UI**, but **all** tasks still go to a **shared** worker queue.
- On conversation delete, optionally **unregister** those rows if you ever created dedicated registry entries (only safe if nothing else uses that agent).

This gives a **product metaphor** (“your agent for this chat”) without **one OS process per chat**.

### 4. Lazy start of the **single** shared worker (minimal UX change)

- Do not start the Agent container with `docker compose up`; start it on **first** task (external script or orchestrator).  
- Still **one** agent for all chats — not per chat, but avoids “agent at build time.”

## Conversation deletion

Today: `DELETE .../conversations/delete-conversation/{chat_id}` removes the conversation and cascades tasks/messages; **agents are untouched**.

If you introduce **conversation-bound** agent IDs:

- Store `agent_id` (or a list) on the conversation or a join table.
- On delete (or after a grace period), call the same cleanup as `DELETE /agents/unregister/{agent_id}` (DB row + `rabbitmq_instance.delete_queue`) **and** ensure the worker process for that ID is stopped (or was ephemeral and already exited).

## Summary

| Need | Current repo | To align with per-chat / ephemeral agents |
|------|----------------|-------------------------------------------|
| Agent created “for this chat” | No; worker registers at startup | Pool queue **or** job-per-task **or** logical session only |
| Worker stops after answer | No; long-running consumer | Job exits, or scale-to-zero, or idle timeout at orchestrator |
| Delete with conversation | Tasks/messages yes; agents no | Store binding + unregister + stop job / purge queue |

Use **option 1** if you want to stay close to the current Python services and RabbitMQ. Use **option 2** if you need **strong isolation** or **pay-per-use** compute. The current **one queue per registered agent ID + one consumer per process** model is the main structural constraint.
