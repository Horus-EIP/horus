# Sprint Plan: Loup - RAG & Agentic Improvements

> **Developer:** Loup Marquez  
> **Branch:** `semester-2-sprint-loup`  
> **Target:** `Second_Semester_Review` → `master`

---

## Assigned Phases

| Phase | Name | Estimated Time |
|-------|------|----------------|
| Phase 5 | ReAct Reasoning Loop | ~25 hours |
| Phase 2b | LLM Integration (Classification & Summary) | ~10 hours |

**Total:** ~35 hours

---

## Merge Order

| Order | Phase | Developer | Depends On |
|-------|-------|-----------|------------|
| 1 | Phase 1: Document Model | Matheus | - |
| 2 | Phase 2a: Auto-Analysis Core | Noah | Phase 1 |
| 3 | Phase 3: Smart Search API | Matheus | Phase 2a |
| 4 | Phase 4: Data Extraction Tools | Noah | Phase 1 |
| **5** | **Phase 5: ReAct Reasoning Loop** | **Loup** | Phase 3, Phase 4 |
| **6** | **Phase 2b: LLM Integration** | **Loup** | Phase 2a |
| 7 | Phase 6: Embedding Upgrade | Matheus | All above |

---

## Git Workflow

```bash
git checkout Second_Semester_Review
git pull origin Second_Semester_Review
git checkout -b semester-2-sprint-loup

# Commits
git commit -m "[Loup] Description of changes"

# When complete - PR to Second_Semester_Review
```

---

## Phase 5: ReAct Reasoning Loop

### Objective

Implement multi-step reasoning that allows agents to think, act, and observe in a loop.

### Tasks

| Task ID | Task | Estimate | Status |
|---------|------|----------|--------|
| L5-T1 | Design ReAct prompt templates (THOUGHT/ACTION/OBSERVATION format) | 2h | ✅ |
| L5-T2 | Create `ReactAgent` class in `src/services/agent/app/ai_agents/react_agent.py` | 4h | ✅ |
| L5-T3 | Implement thought generation method | 2h | ✅ |
| L5-T4 | Implement action selection and response parsing | 3h | ✅ |
| L5-T5 | Implement observation processing | 2h | ✅ |
| L5-T6 | Add execution history tracking | 2h | ✅ |
| L5-T7 | Integrate ReactAgent with existing RAGPipeline | 3h | ✅ |
| L5-T8 | Add source citation in all responses | 2h | ✅ |
| L5-T9 | Write unit tests for ReAct loop | 3h | ✅ |
| L5-T10 | Performance optimization and error handling | 2h | ✅ |

### Files to Create/Modify

- **Create:** `src/services/agent/app/ai_agents/react_agent.py`
- **Modify:** `src/services/agent/app/ai_agents/rag_pipeline.py`
- **Create:** `src/services/agent/app/tests/test_react_agent.py`

### Acceptance Criteria

- [x] ReAct agent can execute multi-step reasoning (up to 5 steps)
- [x] Agent uses tools: `search_knowledge`, `extract_data`, `analyze_payments`, `calc`
- [x] Source citations included in responses
- [x] All tests passing (46/46)

---

## Phase 2b: LLM Integration

### Objective

Add LLM-powered classification and summary generation to Noah's ContentAnalyzer service.

### Tasks

| Task ID | Task | Estimate | Status |
|---------|------|----------|--------|
| L2-T1 | Implement `_classify_with_llm()` method in ContentAnalyzer | 3h | ⬜ |
| L2-T2 | Implement `_generate_summary_with_llm()` method | 2h | ⬜ |
| L2-T3 | Add confidence scoring logic for LLM vs keyword classification | 2h | ⬜ |
| L2-T4 | Integrate LLM methods with Noah's ContentAnalyzer | 2h | ⬜ |
| L2-T5 | Test with various document types | 1h | ⬜ |

### Files to Modify

- **Modify:** `src/services/knowledge-store/app/services/content_analyzer.py`

### Acceptance Criteria

- [ ] LLM classification called when keyword confidence < 0.6
- [ ] LLM summary generation works
- [ ] Graceful fallback if LLM fails

---

## Testing Checklist

- [ ] Unit tests for ReAct loop logic
- [ ] Unit tests for action response parsing
- [ ] Unit tests for LLM classification
- [ ] Integration test: "How much to pay intern?" full flow

---

*Assigned: January 2026*
