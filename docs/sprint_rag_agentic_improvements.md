# Sprint Plan: RAG & Agentic System Improvements

> **Sprint Goal:** Transform the RAG and Agentic systems to enable intelligent document discovery, automatic content analysis, and multi-step reasoning for complex queries.

**Sprint Duration:** 2-3 weeks  
**Priority:** High

---

## Team Assignment

| Developer | Branch | Phases | Hours |
|-----------|--------|--------|-------|
| **Loup** | `semester-2-sprint-loup` | Phase 5, Phase 2b | ~35h |
| **Noah** | `semester-2-sprint-noah` | Phase 2a, Phase 4 | ~35h |
| **Matheus** | `semester-2-sprint-matheus` | Phase 1, Phase 3, Phase 6 | ~25h |

### Individual Sprint Plans

- **[sprint_rag_loup.md](./sprint_rag_loup.md)** - ReAct Reasoning Loop + LLM Integration
- **[sprint_rag_noah.md](./sprint_rag_noah.md)** - Auto-Analysis Pipeline + Data Extraction Tools
- **[sprint_rag_matheus.md](./sprint_rag_matheus.md)** - Document Model + Smart Search API + Embeddings

---

## Merge Order to Second_Semester_Review

**CRITICAL: Phases MUST be merged in this exact order:**

| Order | Phase | Description | Developer | Depends On |
|-------|-------|-------------|-----------|------------|
| **1** | Phase 1 | Enhanced Document Model | Matheus | - |
| **2** | Phase 2a | Auto-Analysis Pipeline (Core) | Noah | Phase 1 |
| **3** | Phase 3 | Smart Search API | Matheus | Phase 2a |
| **4** | Phase 4 | Data Extraction Tools | Noah | Phase 1 |
| **5** | Phase 5 | ReAct Reasoning Loop | Loup | Phase 3, 4 |
| **6** | Phase 2b | LLM Integration | Loup | Phase 2a |
| **7** | Phase 6 | Embedding Model Upgrade | Matheus | All above |

---

## Git Workflow

```
master (production)
  └── Second_Semester_Review (integration)
        ├── semester-2-sprint-loup
        ├── semester-2-sprint-noah
        └── semester-2-sprint-matheus
```

### Process

1. Each dev creates branch from `Second_Semester_Review`
2. Work on assigned phases
3. Create PR to `Second_Semester_Review` **in merge order**
4. Team reviews and tests
5. Merge in correct order
6. Final PR: `Second_Semester_Review` → `master`

---

## Phase Summary

### Phase 1: Enhanced Document Model (Matheus)
Add metadata fields to DocumentModel for filtering:
- `auto_category`, `auto_type`, `auto_summary`
- `entities` (people, companies, amounts, dates)
- `topics`, `confidence_score`

### Phase 2a: Auto-Analysis Pipeline Core (Noah)
Create ContentAnalyzer service:
- Keyword-based category classification
- Entity extraction (regex + spaCy)
- Topic extraction
- Document chunking

### Phase 2b: LLM Integration (Loup)
Add LLM methods to ContentAnalyzer:
- LLM-based classification when keyword confidence low
- LLM-based summary generation

### Phase 3: Smart Search API (Matheus)
New endpoints with filtering:
- `/smart-search` - semantic + metadata filters
- `/search-by-entity` - find by entity
- `/categories` - list categories

### Phase 4: Data Extraction Tools (Noah)
Create agent tools:
- `DataExtractorTool` - extract payments, tables, key-values
- `PaymentAnalyzerTool` - calculate totals, forecasts

### Phase 5: ReAct Reasoning Loop (Loup)
Multi-step reasoning agent:
- THOUGHT → ACTION → OBSERVATION loop
- Uses all tools for complex queries
- Source citations in responses

### Phase 6: Embedding Model Upgrade (Matheus)
Improve retrieval quality:
- Upgrade from MiniLM to BGE model
- Migration script for existing documents

---

## Expected Outcome

**Example Query:** "How much should we pay our intern next month?"

**Current System:** Returns generic text, can't calculate

**After Improvements:**
1. Agent searches for accounting files (even if named `doc1.pdf`)
2. Finds documents with `category=accounting` and `entity=intern`
3. Extracts payment records: `{payee: "intern", amount: 1500, date: "March 2024"}`
4. Calculates forecast: €1,500 for next month
5. Returns answer with source citations

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| File discovery accuracy | ~40% | >90% |
| Structured data extraction | 0% | >80% |
| Complex query completion | ~20% | >75% |

---

## Next Sprint

After completing this sprint, the next planned sprint is:

**[Multi-Agent Collaboration Sprint](./sprint_multi_agent.md)**
- Agent-to-agent communication
- Specialized agents (Researcher, Analyst, Writer)
- Collaborative tasks
- Agent delegation

---

*Created: January 2026*
