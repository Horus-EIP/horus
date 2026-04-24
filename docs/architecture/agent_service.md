# Agent Service — ReAct Reasoning Loop

The Agent service runs the ReAct (Reasoning + Acting) loop that answers user
queries with source-cited responses. It lives in
`src/services/agent/app/ai_agents/` and exposes its HTTP surface through
`src/services/agent/app/agent_server/server.py`.

This page documents the loop itself — the step-by-step flow, the tool
registry, and the failure modes. Source files now carry short docstrings;
long-form narrative lives here.

---

## 1. The ReAct pattern

Horus implements the ReAct pattern from
[Yao et al., 2022](https://arxiv.org/abs/2210.03629): instead of asking the
LLM to answer a question in one shot, we loop over a sequence of
**THOUGHT → ACTION → OBSERVATION** steps. Each step looks like this:

```
THOUGHT: <what should I do next?>
ACTION: <tool_name>(arg1, arg2, ...)
OBSERVATION: <tool result>
```

The loop terminates when the model outputs:

```
THOUGHT: I now have enough information to answer.
FINAL_ANSWER: <answer with [Source: <origin>] citations>
```

## 2. Tool registry

The ReAct agent can call five tools. They are registered at agent
construction time and injected into the system prompt:

| Tool | Signature | Purpose |
|------|-----------|---------|
| `search_knowledge` | `search_knowledge(query)` | RAG retrieval from the Knowledge Store |
| `extract_data` | `extract_data(file_url_or_content, file_type)` | Parse PDF / CSV / TXT |
| `analyze_payments` | `analyze_payments(query)` | Domain-specific payment analytics |
| `calc` | `calc(expression)` | Safe arithmetic evaluator |
| `delegate` | `delegate(to_agent_type, request)` | Hand the task to another agent type |

Each tool call returns an **observation** string plus an optional **source**
identifier that is appended to the final answer's citation list.

## 3. Step limit and timeout

The loop is bounded on two axes:

- **Max steps**: `MAX_REACT_STEPS = 5` (constant in `react_agent.py`).
  Prevents runaway loops when the model keeps picking new actions.
- **Wall-clock timeout**: `DEFAULT_TIMEOUT_SECONDS` from the
  `REACT_TIMEOUT_SECONDS` env var (default 120 s). Protects against slow
  GPU inference on large prompts. Implemented with `asyncio.wait_for`.

When either is hit, the agent builds a best-effort answer from whatever
observations it has collected so far and marks the execution history as
timed-out.

## 4. Execution history

Every query produces an `ExecutionHistory` with:

- `query` — the original user request
- `steps` — ordered list of `ReActStep` (thought / action / observation / final)
- `final_answer` — the answer returned to the caller
- `total_duration_ms` — wall-clock time for the whole loop
- `sources` — deduplicated list of observation sources

The history is serialized in the `/task-result` payload so the MAS
orchestrator can store a full audit trail per conversation.

## 5. Delegation

When the model emits `ACTION: delegate(<agent_type>, <request>)`, the
ReAct agent forwards the sub-request to the configured
`DelegationHandler`. The target agent runs its own ReAct loop and returns
an answer; the parent loop then treats that answer as an observation and
continues. This is how multi-agent coordination is implemented without
any centralized planner — each agent is a peer.

Incoming delegation context (when this agent is the *callee*) is
threaded through `_incoming_delegation_context` and rendered into the
system prompt so the callee can see what was already tried upstream.

## 6. Failure modes

| Failure | Behavior |
|---------|----------|
| Model produces no valid ACTION | Loop nudges with a system observation and retries the same step count |
| Tool raises an exception | Observation contains the error, loop continues (model can try another tool) |
| `asyncio.TimeoutError` | `_build_timeout_answer` returns partial answer with sources gathered so far |
| Any other `Exception` | `_build_error_answer` returns a safe generic error with full traceback logged |
| Max steps exhausted | `_build_exhausted_answer` synthesizes best-effort answer from accumulated context |

In all failure paths the execution history is still returned to the
caller, so the MAS orchestrator can surface exactly what happened to the
end-user if needed.

## 7. Why this design

- **ReAct over Chain-of-Thought** — ReAct lets the model act on the
  world (call tools) between thoughts, which is essential for
  retrieval-augmented tasks. Pure CoT has no feedback loop.
- **Hard step / time limits** — turn-based LLM loops can drift. Bounding
  them makes the agent tractable under load and predictable in tests.
- **Source citations are mandatory** — the system prompt requires
  `[Source: <origin>]` tags in every final answer; it is also enforced
  at citation-attachment time so the caller always has traceable
  evidence.

## 8. Related code

- `src/services/agent/app/ai_agents/react_agent.py` — the loop
- `src/services/agent/app/ai_agents/decision_making_agent.py` — thought generator
- `src/services/agent/app/ai_agents/knowledge_retrieval_agent.py` — RAG hook
- `src/services/agent/app/agent_server/server.py` — HTTP entry point
