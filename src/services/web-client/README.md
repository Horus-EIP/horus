# Web Client

> For the development team. Paths such as `__tests__/` are relative to this
> folder of the git checkout.

The user interface of Horus: chat, conversations, tasks, the knowledge store and the admin pages. A Next.js 16 application (App Router, React 19, Mantine 8, Tailwind CSS 4) on port 3000. Calls to MAS go through the `/api/orchestrator/*` route of the same server, which forwards them to `ORCHESTRATOR_URL`.

## Chat and tasks

- **Sending a question.** The chat sends `POST /tasks/new_task/` with one `Idempotency-Key` per submit, reused on the automatic retries, and gets `202 {task_id}` back at once (`lib/chat/api.ts`).
- **Following it.** Every frame on the conversation WebSocket is a stored event of a task (`lib/chat/task-events.ts`). After a reconnect the client asks `GET /tasks/{task_id}/events?since=<seq>` for what it missed, so an answer that arrived while the tab was closed still shows.
- **Status labels.** Routing, then the agent's name once the task is dispatched. When the agent type's work queue is full the label reads "Busy, position N" until the task is published. A `retrying` status (the agent's first answer was `not_found` or `failed` and MAS asked it once more) clears the streamed preview; the second answer streams from `index` 0.
- **Answers.** An answer lists the passages it cites (title, page) under its text (`components/chat/answer-sources.tsx`); each links to `/knowledge-store?doc=<doc_id>`, which opens that document. The task page (`/tasks/[id]`) shows them too. When a task ends `failed` (for example `reason: "timeout"`), its notice is shown with a Failed label.

## Admin metrics

`/admin/metrics` (`lib/metrics/panels.ts`) queries Prometheus through `/api/metrics`. Besides queue depth, errors and agent counts it shows latency quantiles, "Routing Decisions by Method" and "Routing Time p95 by Method" (`mas_routing_decisions_total`, `mas_routing_decision_seconds`), and "Agent Prompt Tokens per Call" and "MAS Prompt Tokens per Call" (`agent_llm_prompt_tokens`, `mas_llm_prompt_tokens`, sum over count by `call`).

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `ORCHESTRATOR_URL` | MAS base URL used by the server-side proxy and the admin check | `http://127.0.0.1:8000` |
| `NEXT_PUBLIC_WS_URL` | WebSocket base URL of MAS (a Docker-internal host name is ignored in the browser) | the page's host name on port 8000 |
| `NEXT_PUBLIC_KNOWLEDGE_STORE_URL` | Knowledge store base URL | `http://localhost:8080` |
| `NEXT_PUBLIC_KNOWLEDGE_STORE_API_PREFIX` | Path prefix of the knowledge store behind a gateway | empty |
| `PROMETHEUS_URL`, `LOKI_URL`, `TEMPO_URL` | Backends of the admin metrics, logs and traces pages | `http://127.0.0.1:9090`, `:3100`, `:3200` |

## Development

```bash
cd src/services/web-client
npm ci
npm run dev
```

Open http://localhost:3000. Unit tests (Vitest, `__tests__/`) and the type check:

```bash
npx vitest run
npx tsc --noEmit -p tsconfig.json
```
