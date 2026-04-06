# Sprint Plan: Noah - RAG & Agentic Improvements

> **Developer:** Noah Gibelli  
> **Branch:** `semester-2-sprint-noah`  
> **Target:** `Second_Semester_Review` → `master`

---

## Assigned Phases

| Phase | Name | Estimated Time |
|-------|------|----------------|
| Phase 2a | Auto-Analysis Pipeline (Core) | ~20 hours |
| Phase 4 | Data Extraction Tools | ~15 hours |

**Total:** ~35 hours

---

## Merge Order

| Order | Phase | Developer | Depends On |
|-------|-------|-----------|------------|
| 1 | Phase 1: Document Model | Matheus | - |
| **2** | **Phase 2a: Auto-Analysis Core** | **Noah** | Phase 1 |
| 3 | Phase 3: Smart Search API | Matheus | Phase 2a |
| **4** | **Phase 4: Data Extraction Tools** | **Noah** | Phase 1 |
| 5 | Phase 5: ReAct Reasoning Loop | Loup | Phase 3, Phase 4 |
| 6 | Phase 2b: LLM Integration | Loup | Phase 2a |
| 7 | Phase 6: Embedding Upgrade | Matheus | All above |

---

## Git Workflow

```bash
git checkout Second_Semester_Review
git pull origin Second_Semester_Review
git checkout -b semester-2-sprint-noah

# Commits
git commit -m "[Noah] Description of changes"

# When complete - PR to Second_Semester_Review
```

---

## Phase 2a: Auto-Analysis Pipeline (Core)

### Objective

Create the `ContentAnalyzer` service that automatically analyzes uploaded documents to extract categories, entities, and topics.

### Tasks

| Task ID | Task | Estimate | Status |
|---------|------|----------|--------|
| N2-T1 | Create `ContentAnalyzer` class in `src/services/knowledge-store/app/services/content_analyzer.py` | 2h | ⬜ |
| N2-T2 | Implement keyword-based category classification | 2h | ⬜ |
| N2-T3 | Implement entity extraction using regex (amounts, dates) | 2h | ⬜ |
| N2-T4 | Add spaCy NER for people and company extraction | 2h | ⬜ |
| N2-T5 | Implement topic extraction | 2h | ⬜ |
| N2-T6 | Implement basic summary generation (non-LLM) | 1h | ⬜ |
| N2-T7 | Implement document type detection | 1h | ⬜ |
| N2-T8 | Create `DocumentChunker` class in `src/services/knowledge-store/app/services/document_chunker.py` | 3h | ⬜ |
| N2-T9 | Integrate ContentAnalyzer into upload endpoint | 2h | ⬜ |
| N2-T10 | Write integration tests | 3h | ⬜ |

### Files to Create/Modify

- **Create:** `src/services/knowledge-store/app/services/content_analyzer.py`
- **Create:** `src/services/knowledge-store/app/services/document_chunker.py`
- **Modify:** `src/services/knowledge-store/app/api/routes/store.py`
- **Modify:** `src/services/knowledge-store/requirements.txt` (add spacy)

### Categories to Support

```
accounting, hr, legal, operations, sales, technical, marketing, general
```

### Entities to Extract

- People: Names, roles (intern, employee, contractor, supplier)
- Companies: Organization names
- Amounts: Currency values (€, $, EUR, USD)
- Dates: Various formats

### Acceptance Criteria

- [ ] ContentAnalyzer extracts category with >70% accuracy
- [ ] Entity extraction finds amounts, dates, people
- [ ] DocumentChunker splits large documents into chunks
- [ ] Upload endpoint returns auto_analysis in response

---

## Phase 4: Data Extraction Tools

### Objective

Create agent tools that extract structured data from documents.

### Tasks

| Task ID | Task | Estimate | Status |
|---------|------|----------|--------|
| N4-T1 | Create `DataExtractorTool` class in `src/services/agent/app/ai_agents/data_extractor_tool.py` | 2h | ⬜ |
| N4-T2 | Implement `_extract_payments()` method | 3h | ⬜ |
| N4-T3 | Implement `_extract_tables()` method | 2h | ⬜ |
| N4-T4 | Implement `_extract_key_values()` method | 1h | ⬜ |
| N4-T5 | Create `PaymentAnalyzerTool` class | 3h | ⬜ |
| N4-T6 | Implement operations: total, average, by_payee, forecast | 2h | ⬜ |
| N4-T7 | Register tools in ToolRegistry | 1h | ⬜ |
| N4-T8 | Write unit tests | 3h | ⬜ |

### Files to Create/Modify

- **Create:** `src/services/agent/app/ai_agents/data_extractor_tool.py`
- **Modify:** `src/services/agent/app/ai_agents/rag_pipeline.py`
- **Create:** `src/services/agent/app/tests/test_data_extractor.py`

### Acceptance Criteria

- [ ] DataExtractorTool extracts payment records
- [ ] PaymentAnalyzerTool calculates totals and forecasts
- [ ] Tools registered in ToolRegistry
- [ ] All tests passing

---

## Testing Checklist

- [ ] Category classification accuracy
- [ ] Entity extraction (amounts, dates, people)
- [ ] Document chunking
- [ ] Payment extraction from CSV
- [ ] PaymentAnalyzerTool calculations

---

## Notes

- Add `spacy>=3.5.0` to requirements.txt
- Download model: `python -m spacy download en_core_web_sm`
- Leave placeholder methods for Loup's LLM integration

---

*Assigned: January 2026*
