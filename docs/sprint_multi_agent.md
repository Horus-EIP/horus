# Sprint Plan: Multi-Agent Collaboration

> **Sprint Goal:** Enable agents to communicate, collaborate, and delegate tasks to specialized agents for complex problem solving.

**Total Duration:** 4 weeks (2 sprints of 2 weeks each)  
**Priority:** Medium (after RAG improvements sprint)  
**Prerequisites:** RAG & Agentic Improvements Sprint completed

---

## Parallel Work — No Blockers

Each developer can work **independently** without waiting for others:

| Developer | Strategy | How |
|-----------|----------|-----|
| **Loup** | Standalone | Communication & Delegation are self-contained (Delegation uses his own Sprint 1 work) |
| **Noah** | In-memory execution | Specialized Agents + Collaborative Tasks use sync in-memory handoff; wire to RabbitMQ at merge |
| **Matheus** | Mock data | All UI built against mock JSON; wire to real API at merge |

**Day 0:** All three align on shared contracts (schemas, agent types, API shapes) — see [Shared Contracts](#shared-contracts) below.

---

## Team Assignment

| Developer | Branch | Sprints | Hours |
|-----------|--------|---------|-------|
| **Loup** | `semester-2-sprint-multiagent-loup` | Sprint 1, Sprint 2 | ~30h |
| **Noah** | `semester-2-sprint-multiagent-noah` | Sprint 1, Sprint 2 | ~30h |
| **Matheus** | `semester-2-sprint-multiagent-matheus` | Sprint 1, Sprint 2 | ~15h |

---

## Merge Order (flexible — integration when ready)

| Order | Sprint | Description | Developer |
|-------|--------|-------------|-----------|
| 1 | Sprint 1 | Agent-to-Agent Communication | Loup |
| 2 | Sprint 1 | Specialized Agents | Noah |
| 3 | Sprint 1 | UI Foundations | Matheus |
| 4 | Sprint 2 | Agent Delegation | Loup |
| 5 | Sprint 2 | Collaborative Tasks | Noah |
| 6 | Sprint 2 | UI Completion | Matheus |

---

## Shared Contracts

Define these **before** Sprint 1 starts so everyone codes against the same interfaces.

### Agent Types (enum)

```
researcher | analyst | writer | general
```

### AgentMessage Schema

```python
class AgentMessage:
    id: str
    sender_agent_id: str
    receiver_agent_id: str
    message_type: str  # "request", "response", "delegation", "result"
    content: dict
    conversation_id: str
    timestamp: datetime
    requires_response: bool
```

### API Response Shapes (for UI mocks)

- `GET /agents` — include `agent_type` field
- `GET /tasks/:id` — include `subtasks`, `agent_messages`, `delegation_chain`

### Integration (after merge)

| Component | Action |
|-----------|--------|
| Noah's Collaborative Tasks | Wire to Loup's RabbitMQ for async agent handoff (optional; in-memory works) |
| Matheus's UI | Swap mock data for real API calls |

---

## Architecture Overview

### Current (Single Agent per Task)

```
User → Orchestrator → Agent → Response
```

### Target (Multi-Agent Collaboration)

```
User → Orchestrator → Task Decomposition
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
    ┌──────────┐     ┌──────────┐     ┌──────────┐
    │Researcher│ ←─► │ Analyst  │ ←─► │  Writer  │
    │  Agent   │     │  Agent   │     │  Agent   │
    └──────────┘     └──────────┘     └──────────┘
         │                 │                 │
         └─────────────────┼─────────────────┘
                           ▼
                    Final Response
```

---

## Sprint 1: Communication, Specialized Agents & UI Foundations (Weeks 1-2)

**Developers:** Loup + Noah + Matheus  
**Estimated Time:** Loup ~15h, Noah ~15h, Matheus ~7h  
**Deliverable:** Agents can communicate and register with specialized types; UI scaffolding and agent type visuals are in place.

### 1.1 — Agent-to-Agent Communication (Loup)

**Unblocked:** Fully standalone. No dependencies on other devs.

#### Objective

Enable agents to send messages to each other through a message bus.

#### Tasks

| Task ID | Task | Estimate | Status |
|---------|------|----------|--------|
| L1-T1 | Design agent communication protocol (message format) | 2h | ⬜ |
| L1-T2 | Create `AgentMessage` model (sender, receiver, content, type) | 1h | ⬜ |
| L1-T3 | Extend RabbitMQ to support agent-to-agent queues | 3h | ⬜ |
| L1-T4 | Create `AgentCommunicator` class for sending/receiving messages | 3h | ⬜ |
| L1-T5 | Add message handlers in agent server | 2h | ⬜ |
| L1-T6 | Implement message acknowledgment and timeout | 2h | ⬜ |
| L1-T7 | Write unit tests | 2h | ⬜ |

#### Files to Create/Modify

- **Create:** `src/services/mas/core/agent_communication.py`
- **Create:** `src/services/mas/schemas/agent_message.py`
- **Modify:** `src/services/mas/core/rabbitmq_tool.py`
- **Modify:** `src/services/agent/app/agent_server/server.py`

#### Message Format

```python
class AgentMessage:
    id: str
    sender_agent_id: str
    receiver_agent_id: str
    message_type: str  # "request", "response", "delegation", "result"
    content: dict
    conversation_id: str
    timestamp: datetime
    requires_response: bool
```

#### Acceptance Criteria

- [ ] Agent A can send message to Agent B
- [ ] Agent B receives and processes message
- [ ] Messages are persisted for debugging
- [ ] Timeout handling for unresponsive agents

---

### 1.2 — Specialized Agents (Noah)

**Unblocked:** Work independently. Use in-memory handoff for orchestration; wire to RabbitMQ when Loup's Communication is merged.

#### Objective

Create different agent types with specialized capabilities.

#### Tasks

| Task ID | Task | Estimate | Status |
|---------|------|----------|--------|
| N2-T1 | Define agent specialization schema (capabilities, tools) | 2h | ⬜ |
| N2-T2 | Create `ResearcherAgent` (document search, summarization) | 3h | ⬜ |
| N2-T3 | Create `AnalystAgent` (data extraction, calculations) | 3h | ⬜ |
| N2-T4 | Create `WriterAgent` (report generation, formatting) | 3h | ⬜ |
| N2-T5 | Add agent type to registration process | 2h | ⬜ |
| N2-T6 | Write unit tests | 2h | ⬜ |

#### Files to Create/Modify

- **Create:** `src/services/agent/app/specialized/researcher_agent.py`
- **Create:** `src/services/agent/app/specialized/analyst_agent.py`
- **Create:** `src/services/agent/app/specialized/writer_agent.py`
- **Modify:** `src/services/mas/agents/routes.py` (agent type field)
- **Modify:** `src/services/mas/db/models.py` (Agent model)

#### Agent Types

| Agent Type | Capabilities | Tools |
|------------|--------------|-------|
| **Researcher** | Find documents, summarize | `search_knowledge`, `summarize` |
| **Analyst** | Extract data, calculate | `extract_data`, `analyze_payments`, `calc` |
| **Writer** | Generate reports, format | `generate_report`, `format_text` |
| **General** | All capabilities (default) | All tools |

#### Acceptance Criteria

- [ ] Agents can register with a type
- [ ] Each type has specific tools available
- [ ] Orchestrator knows agent capabilities
- [ ] Can spawn specialized agent instances

---

### 1.3 — UI Foundations (Matheus)

**Unblocked:** Work independently. Use mock data (see `docs/mocks/` or inline fixtures); wire to real API at merge.

#### Objective

Scaffold the multi-agent UI components and implement agent type visuals.

#### Tasks

| Task ID | Task | Estimate | Status |
|---------|------|----------|--------|
| M1-T1 | Add agent type icons and indicators (use mock agent types) | 2h | ⬜ |
| M1-T2 | Create collaboration view scaffold component with mock data | 3h | ⬜ |
| M1-T3 | Update admin agents page with type badges | 2h | ⬜ |

#### Files to Create/Modify

- **Create:** `src/services/web-client/components/agents/collaboration-view.tsx` (scaffold)
- **Modify:** `src/services/web-client/app/(protected)/admin/agents/page.tsx`

#### UI Components

| Component | Description |
|-----------|-------------|
| Agent Type Badge | Visual indicator of agent specialization (Researcher, Analyst, Writer) |
| Collaboration View (scaffold) | Base layout for showing agents working together |

#### Acceptance Criteria

- [ ] Agent types clearly indicated with icons/badges in admin panel
- [ ] Collaboration view scaffold renders and is ready for Sprint 2 data

---

### Sprint 1 Definition of Done

- [ ] All communication and specialization features merged
- [ ] Agents can exchange messages and register with types
- [ ] UI shows agent types and has collaboration view scaffolded
- [ ] Unit tests pass

---

## Sprint 2: Collaborative Tasks, Delegation & UI Completion (Weeks 3-4)

**Developers:** Loup + Noah + Matheus  
**Estimated Time:** Loup ~15h, Noah ~15h, Matheus ~8h  
**Deliverable:** Agents can collaborate on complex tasks and delegate mid-task; full UI visualization of multi-agent workflows.

### 2.1 — Agent Delegation (Loup)

**Unblocked:** Depends only on your own Sprint 1 (Communication). No other dev blocks you.

#### Objective

Allow an agent to delegate part of its work to another agent mid-task.

#### Tasks

| Task ID | Task | Estimate | Status |
|---------|------|----------|--------|
| L4-T1 | Design delegation protocol | 2h | ⬜ |
| L4-T2 | Add `delegate` action to ReAct agent | 3h | ⬜ |
| L4-T3 | Implement delegation request/response handling | 3h | ⬜ |
| L4-T4 | Add delegation to agent capabilities discovery | 2h | ⬜ |
| L4-T5 | Implement delegation chain tracking (prevent loops) | 2h | ⬜ |
| L4-T6 | Write integration tests | 3h | ⬜ |

#### Files to Create/Modify

- **Modify:** `src/services/agent/app/ai_agents/react_agent.py`
- **Create:** `src/services/agent/app/ai_agents/delegation_handler.py`
- **Modify:** `src/services/mas/core/agent_communication.py`

#### Delegation Flow

```
ResearcherAgent working on task:
  │
  ├─ THOUGHT: I found financial data but need calculations
  ├─ ACTION: delegate
  ├─ ACTION_INPUT: {
  │    "to_agent_type": "analyst",
  │    "request": "Calculate total payments from this data",
  │    "data": {...}
  │  }
  │
  ▼
AnalystAgent receives delegation:
  │
  ├─ Processes calculation request
  ├─ Returns result to ResearcherAgent
  │
  ▼
ResearcherAgent continues with result
```

#### Acceptance Criteria

- [ ] Agent can delegate to another agent type
- [ ] Delegation results return to original agent
- [ ] Delegation loops prevented (max depth)
- [ ] Timeout handling for delegations

---

### 2.2 — Collaborative Tasks (Noah)

**Unblocked:** Work independently. Use sync in-memory execution (orchestrator runs agents sequentially, passes results in memory). Wire to message bus at merge when Loup's Communication is available.

#### Objective

Enable multiple agents to work together on a single task.

#### Tasks

| Task ID | Task | Estimate | Status |
|---------|------|----------|--------|
| N3-T1 | Design task decomposition logic in orchestrator | 3h | ⬜ |
| N3-T2 | Create `CollaborativeTask` model (subtasks, assignments) | 2h | ⬜ |
| N3-T3 | Implement subtask creation, assignment, and in-memory execution (sequential handoff) | 3h | ⬜ |
| N3-T4 | Implement result aggregation from multiple agents | 3h | ⬜ |
| N3-T5 | Add dependency handling (subtask B waits for subtask A) | 2h | ⬜ |
| N3-T6 | Write integration tests | 2h | ⬜ |

#### Files to Create/Modify

- **Create:** `src/services/mas/tasks/collaborative_task.py`
- **Modify:** `src/services/mas/tasks/task_tool_functions.py`
- **Modify:** `src/services/mas/tasks/routes.py`

#### Collaborative Task Flow

```
1. User: "Analyze sales data and create a report"

2. Orchestrator decomposes:
   - Subtask 1: Find sales documents (Researcher)
   - Subtask 2: Extract and analyze data (Analyst) [depends on 1]
   - Subtask 3: Write report (Writer) [depends on 2]

3. Execute in order with handoffs

4. Aggregate final result
```

#### Acceptance Criteria

- [ ] Complex tasks decompose into subtasks
- [ ] Subtasks assigned to appropriate agent types
- [ ] Results aggregate into final response
- [ ] Dependencies respected (order of execution)

---

### 2.3 — UI Completion (Matheus)

**Unblocked:** Work independently. Use mock data for subtasks, message flow, delegation chains. Wire to real API at merge.

#### Objective

Finish all multi-agent UI components with live data from collaboration and delegation.

#### Tasks

| Task ID | Task | Estimate | Status |
|---------|------|----------|--------|
| M2-T1 | Show subtask breakdown in task detail view (mock data) | 3h | ⬜ |
| M2-T2 | Display agent-to-agent message flow (mock data) | 3h | ⬜ |
| M2-T3 | Show delegation chains in UI (mock data) | 2h | ⬜ |

#### Files to Create/Modify

- **Create:** `src/services/web-client/components/tasks/subtask-tree.tsx`
- **Modify:** `src/services/web-client/components/agents/collaboration-view.tsx` (wire up live data)
- **Modify:** `src/services/web-client/app/(protected)/tasks/[id]/page.tsx`

#### UI Components

| Component | Description |
|-----------|-------------|
| Subtask Tree | Hierarchical view of task decomposition |
| Message Flow | Timeline of agent communications |
| Delegation Chain | Visual path of delegation handoffs |

#### Acceptance Criteria

- [ ] Can see which agents collaborated on a task
- [ ] Subtask breakdown visible in task details
- [ ] Delegation chains visualized
- [ ] Message flow timeline displays correctly

---

### Sprint 2 Definition of Done

- [ ] Delegation, collaborative tasks, and full UI merged
- [ ] Agents can delegate mid-task with loop prevention
- [ ] Complex tasks decompose and execute across multiple agents
- [ ] Multi-agent collaboration is fully visible in the UI
- [ ] All tests pass

---

## Example Use Case

**User Query:** "Analyze our Q4 sales performance and write a summary report"

### Without Multi-Agent (Current)

```
Single Agent tries to do everything → Often incomplete or generic response
```

### With Multi-Agent (After Sprint 2)

```
Step 1: Orchestrator decomposes task
        ├── Subtask 1: Find Q4 sales documents
        ├── Subtask 2: Extract and analyze sales data
        └── Subtask 3: Write summary report

Step 2: Assign to specialized agents
        ├── Researcher → Subtask 1
        ├── Analyst → Subtask 2
        └── Writer → Subtask 3

Step 3: Execute with collaboration
        Researcher finds 5 sales documents
              │
              ▼ (passes documents)
        Analyst extracts: Revenue +15%, Top product: X
              │
              ▼ (passes analysis)
        Writer creates formatted report

Step 4: Return comprehensive report to user
```

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Complex task completion | ~30% | >80% |
| Response quality (multi-step) | Low | High |
| Task types supported | Limited | Expanded |

---

## Dependencies

This sprint depends on completing the RAG & Agentic Improvements sprint first:
- ReAct reasoning — needed for delegation
- Data extraction tools — needed for Analyst agent
- Smart search — needed for Researcher agent

---

*Created: January 2026*  
*Last Updated: March 2026*  
*Status: Planning*
