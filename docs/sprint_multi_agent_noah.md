# Multi-Agent Sprint — Noah

**Branch:** `semester-2-sprint-multiagent-noah`  
**Total Hours:** ~30h  
**Duration:** 4 weeks (Sprint 1 + Sprint 2)

**You are unblocked:** Work independently. Use in-memory/sync handoff for orchestration; wire to Loup's RabbitMQ when merged.

---

## Sprint 1: Specialized Agents (Weeks 1-2)

**Estimated Time:** ~15h  
**Blockers:** None — use shared contracts (agent types) from Day 0  
**Deliverable:** Different agent types exist with specialized capabilities and tools.

### Objective

Create different agent types with specialized capabilities.

### Tasks

| Task ID | Task | Estimate | Status |
|---------|------|----------|--------|
| N2-T1 | Define agent specialization schema (capabilities, tools) | 2h | ⬜ |
| N2-T2 | Create `ResearcherAgent` (document search, summarization) | 3h | ⬜ |
| N2-T3 | Create `AnalystAgent` (data extraction, calculations) | 3h | ⬜ |
| N2-T4 | Create `WriterAgent` (report generation, formatting) | 3h | ⬜ |
| N2-T5 | Add agent type to registration process | 2h | ⬜ |
| N2-T6 | Write unit tests | 2h | ⬜ |

### Files to Create/Modify

- **Create:** `src/services/agent/app/specialized/researcher_agent.py`
- **Create:** `src/services/agent/app/specialized/analyst_agent.py`
- **Create:** `src/services/agent/app/specialized/writer_agent.py`
- **Modify:** `src/services/mas/agents/routes.py` (agent type field)
- **Modify:** `src/services/mas/db/models.py` (Agent model)

### Agent Types

| Agent Type | Capabilities | Tools |
|------------|--------------|-------|
| **Researcher** | Find documents, summarize | `search_knowledge`, `summarize` |
| **Analyst** | Extract data, calculate | `extract_data`, `analyze_payments`, `calc` |
| **Writer** | Generate reports, format | `generate_report`, `format_text` |
| **General** | All capabilities (default) | All tools |

### Acceptance Criteria

- [ ] Agents can register with a type
- [ ] Each type has specific tools available
- [ ] Orchestrator knows agent capabilities
- [ ] Can spawn specialized agent instances

---

## Sprint 2: Collaborative Tasks (Weeks 3-4)

**Estimated Time:** ~15h  
**Blockers:** None — use in-memory sequential execution (orchestrator runs agents one-by-one, passes results in memory). Wire to message bus at merge.  
**Deliverable:** Multiple agents can work together on a single complex task.

### Objective

Enable multiple agents to work together on a single task.

### Tasks

| Task ID | Task | Estimate | Status |
|---------|------|----------|--------|
| N3-T1 | Design task decomposition logic in orchestrator | 3h | ⬜ |
| N3-T2 | Create `CollaborativeTask` model (subtasks, assignments) | 2h | ⬜ |
| N3-T3 | Implement subtask creation, assignment, and in-memory execution (sequential handoff) | 3h | ⬜ |
| N3-T4 | Implement result aggregation from multiple agents | 3h | ⬜ |
| N3-T5 | Add dependency handling (subtask B waits for subtask A) | 2h | ⬜ |
| N3-T6 | Write integration tests | 2h | ⬜ |

### Files to Create/Modify

- **Create:** `src/services/mas/tasks/collaborative_task.py`
- **Modify:** `src/services/mas/tasks/task_tool_functions.py`
- **Modify:** `src/services/mas/tasks/routes.py`

### Collaborative Task Flow

```
1. User: "Analyze sales data and create a report"

2. Orchestrator decomposes:
   - Subtask 1: Find sales documents (Researcher)
   - Subtask 2: Extract and analyze data (Analyst) [depends on 1]
   - Subtask 3: Write report (Writer) [depends on 2]

3. Execute in order with handoffs

4. Aggregate final result
```

### Acceptance Criteria

- [ ] Complex tasks decompose into subtasks
- [ ] Subtasks assigned to appropriate agent types
- [ ] Results aggregate into final response
- [ ] Dependencies respected (order of execution)

---

*Reference: [sprint_multi_agent.md](sprint_multi_agent.md)*
