# Multi-Agent Sprint — Loup

**Branch:** `semester-2-sprint-multiagent-loup`  
**Total Hours:** ~30h  
**Duration:** 4 weeks (Sprint 1 + Sprint 2)

**You are unblocked:** No dependencies on Noah or Matheus. Sprint 2 (Delegation) uses your own Sprint 1 (Communication).

---

## Sprint 1: Agent-to-Agent Communication (Weeks 1-2)

**Estimated Time:** ~15h  
**Blockers:** None — fully standalone  
**Deliverable:** Agents can send and receive messages through a message bus.

### Objective

Enable agents to send messages to each other through a message bus.

### Tasks

| Task ID | Task | Estimate | Status |
|---------|------|----------|--------|
| L1-T1 | Design agent communication protocol (message format) | 2h | ✅ |
| L1-T2 | Create `AgentMessage` model (sender, receiver, content, type) | 1h | ✅ |
| L1-T3 | Extend RabbitMQ to support agent-to-agent queues | 3h | ✅ |
| L1-T4 | Create `AgentCommunicator` class for sending/receiving messages | 3h | ✅ |
| L1-T5 | Add message handlers in agent server | 2h | ✅ |
| L1-T6 | Implement message acknowledgment and timeout | 2h | ✅ |
| L1-T7 | Write unit tests | 2h | ✅ |

### Files to Create/Modify

- **Create:** `src/services/mas/core/agent_communication.py`
- **Create:** `src/services/mas/schemas/agent_message.py`
- **Modify:** `src/services/mas/core/rabbitmq_tool.py`
- **Modify:** `src/services/agent/app/agent_server/server.py`

### Message Format

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

### Acceptance Criteria

- [x] Agent A can send message to Agent B
- [x] Agent B receives and processes message
- [x] Messages are persisted for debugging
- [x] Timeout handling for unresponsive agents

---

## Sprint 2: Agent Delegation (Weeks 3-4)

**Estimated Time:** ~15h  
**Depends On:** Your own Sprint 1 (Communication) — no other dev blocks you  
**Deliverable:** Agents can delegate part of their work to another agent mid-task.

### Objective

Allow an agent to delegate part of its work to another agent mid-task.

### Tasks

| Task ID | Task | Estimate | Status |
|---------|------|----------|--------|
| L4-T1 | Design delegation protocol | 2h | ✅ |
| L4-T2 | Add `delegate` action to ReAct agent | 3h | ✅ |
| L4-T3 | Implement delegation request/response handling | 3h | ✅ |
| L4-T4 | Add delegation to agent capabilities discovery | 2h | ✅ |
| L4-T5 | Implement delegation chain tracking (prevent loops) | 2h | ✅ |
| L4-T6 | Write integration tests | 3h | ✅ |

### Files to Create/Modify

- **Modify:** `src/services/agent/app/ai_agents/react_agent.py`
- **Create:** `src/services/agent/app/ai_agents/delegation_handler.py`
- **Modify:** `src/services/mas/core/agent_communication.py`

### Delegation Flow

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

### Acceptance Criteria

- [x] Agent can delegate to another agent type
- [x] Delegation results return to original agent
- [x] Delegation loops prevented (max depth)
- [x] Timeout handling for delegations

---

*Reference: [sprint_multi_agent.md](sprint_multi_agent.md)*
