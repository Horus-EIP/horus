# Multi-Agent Sprint — Matheus

**Branch:** `semester-2-sprint-multiagent-matheus`  
**Total Hours:** ~15h  
**Duration:** 4 weeks (Sprint 1 + Sprint 2)

**You are unblocked:** Work independently. Use mock data for all UI; wire to real API when backend is merged.

---

## Sprint 1: UI Foundations (Weeks 1-2)

**Estimated Time:** ~7h  
**Blockers:** None — use mock agent types and shared contracts from Day 0  
**Deliverable:** Agent type visuals in admin panel and collaboration view scaffold ready for Sprint 2.

### Objective

Scaffold the multi-agent UI components and implement agent type visuals.

### Tasks

| Task ID | Task | Estimate | Status |
|---------|------|----------|--------|
| M1-T1 | Add agent type icons and indicators (use mock agent types) | 2h | ⬜ |
| M1-T2 | Create collaboration view scaffold component with mock data | 3h | ⬜ |
| M1-T3 | Update admin agents page with type badges | 2h | ⬜ |

### Files to Create/Modify

- **Create:** `src/services/web-client/components/agents/collaboration-view.tsx` (scaffold)
- **Modify:** `src/services/web-client/app/(protected)/admin/agents/page.tsx`

### UI Components

| Component | Description |
|-----------|-------------|
| Agent Type Badge | Visual indicator of agent specialization (Researcher, Analyst, Writer) |
| Collaboration View (scaffold) | Base layout for showing agents working together |

### Acceptance Criteria

- [ ] Agent types clearly indicated with icons/badges in admin panel
- [ ] Collaboration view scaffold renders and is ready for Sprint 2 data

---

## Sprint 2: UI Completion (Weeks 3-4)

**Estimated Time:** ~8h  
**Blockers:** None — use mock data for subtasks, message flow, delegation chains. Wire to real API at merge.  
**Deliverable:** Full UI visualization of multi-agent collaboration, delegation chains, and message flow.

### Objective

Finish all multi-agent UI components with live data from collaboration and delegation.

### Tasks

| Task ID | Task | Estimate | Status |
|---------|------|----------|--------|
| M2-T1 | Show subtask breakdown in task detail view (mock data) | 3h | ⬜ |
| M2-T2 | Display agent-to-agent message flow (mock data) | 3h | ⬜ |
| M2-T3 | Show delegation chains in UI (mock data) | 2h | ⬜ |

### Files to Create/Modify

- **Create:** `src/services/web-client/components/tasks/subtask-tree.tsx`
- **Modify:** `src/services/web-client/components/agents/collaboration-view.tsx` (wire up live data)
- **Modify:** `src/services/web-client/app/(protected)/tasks/[id]/page.tsx`

### UI Components

| Component | Description |
|-----------|-------------|
| Subtask Tree | Hierarchical view of task decomposition |
| Message Flow | Timeline of agent communications |
| Delegation Chain | Visual path of delegation handoffs |

### Acceptance Criteria

- [ ] Can see which agents collaborated on a task
- [ ] Subtask breakdown visible in task details
- [ ] Delegation chains visualized
- [ ] Message flow timeline displays correctly

---

*Reference: [sprint_multi_agent.md](sprint_multi_agent.md)*
