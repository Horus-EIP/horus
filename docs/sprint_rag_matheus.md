# Sprint Plan: Matheus - RAG & Agentic Improvements

> **Developer:** Matheus Freixo  
> **Branch:** `semester-2-sprint-matheus`  
> **Target:** `Second_Semester_Review` → `master`

---

## Assigned Phases

| Phase | Name | Estimated Time |
|-------|------|----------------|
| Phase 1 | Enhanced Document Model | ~6 hours |
| Phase 3 | Smart Search API | ~12 hours |
| Phase 6 | Embedding Model Upgrade | ~7 hours |

**Total:** ~25 hours

---

## Merge Order

| Order | Phase | Developer | Depends On |
|-------|-------|-----------|------------|
| **1** | **Phase 1: Document Model** | **Matheus** | - |
| 2 | Phase 2a: Auto-Analysis Core | Noah | Phase 1 |
| **3** | **Phase 3: Smart Search API** | **Matheus** | Phase 2a |
| 4 | Phase 4: Data Extraction Tools | Noah | Phase 1 |
| 5 | Phase 5: ReAct Reasoning Loop | Loup | Phase 3, Phase 4 |
| 6 | Phase 2b: LLM Integration | Loup | Phase 2a |
| **7** | **Phase 6: Embedding Upgrade** | **Matheus** | All above |

---

## Git Workflow

```bash
git checkout Second_Semester_Review
git pull origin Second_Semester_Review
git checkout -b semester-2-sprint-matheus

# Commits
git commit -m "[Matheus] Description of changes"

# When complete - PR to Second_Semester_Review
```

---

## Phase 1: Enhanced Document Model

### Objective

Extend the document model to support metadata fields for filtering.

### Tasks

| Task ID | Task | Estimate | Status |
|---------|------|----------|--------|
| M1-T1 | Update `DocumentModel` in `document.py` with new fields | 1h | ⬜ |
| M1-T2 | Add `EntityModel` class for structured entity storage | 30min | ⬜ |
| M1-T3 | Update `store_file()` in `file_service.py` to store metadata | 2h | ⬜ |
| M1-T4 | Add `query_with_filters()` function | 1h | ⬜ |
| M1-T5 | Update API schemas | 30min | ⬜ |
| M1-T6 | Write unit tests | 1h | ⬜ |

### Files to Modify

- **Modify:** `src/services/knowledge-store/app/chroma_db/models/document.py`
- **Modify:** `src/services/knowledge-store/app/chroma_db/services/file_service.py`

### New DocumentModel Fields

```
Auto-generated:
- auto_category: str
- auto_type: str
- auto_summary: str
- entities: EntityModel (people, companies, amounts, dates)
- topics: List[str]
- confidence_score: float
- analyzed_at: datetime

User-provided:
- user_category: str
- user_tags: List[str]

Chunking:
- chunk_count: int
- is_chunk: bool
- parent_id: str
- chunk_index: int
```

### Acceptance Criteria

- [ ] DocumentModel has all new fields
- [ ] ChromaDB stores metadata correctly
- [ ] Backward compatible with existing documents

---

## Phase 3: Smart Search API

### Objective

Create search endpoints with metadata filtering.

### Tasks

| Task ID | Task | Estimate | Status |
|---------|------|----------|--------|
| M3-T1 | Create `/smart-search` endpoint with filters | 3h | ⬜ |
| M3-T2 | Implement ChromaDB where clause building | 2h | ⬜ |
| M3-T3 | Create `/search-by-entity` endpoint | 2h | ⬜ |
| M3-T4 | Create `/categories` endpoint | 1h | ⬜ |
| M3-T5 | Update Agent's `KnowledgeStoreClient` with new methods | 2h | ⬜ |
| M3-T6 | Write API tests | 2h | ⬜ |

### Files to Modify

- **Modify:** `src/services/knowledge-store/app/api/routes/store.py`
- **Modify:** `src/services/agent/app/ai_agents/knowledge_store_client.py`

### New Endpoints

- `GET /api/knowledge-store/smart-search` - query, category, entity, min_confidence
- `GET /api/knowledge-store/search-by-entity` - entity, entity_type
- `GET /api/knowledge-store/categories` - list categories with counts

### Acceptance Criteria

- [ ] Smart search filters by category
- [ ] Smart search filters by entity
- [ ] Categories endpoint returns counts
- [ ] Agent client has new methods

---

## Phase 6: Embedding Model Upgrade

### Objective

Upgrade to better embedding model for improved retrieval.

### Tasks

| Task ID | Task | Estimate | Status |
|---------|------|----------|--------|
| M6-T1 | Research embedding models | 1h | ⬜ |
| M6-T2 | Update model in `setup.py` | 1h | ⬜ |
| M6-T3 | Create migration script | 2h | ⬜ |
| M6-T4 | Update Dockerfile | 1h | ⬜ |
| M6-T5 | Test retrieval quality | 2h | ⬜ |

### Files to Modify

- **Modify:** `src/services/knowledge-store/app/chroma_db/setup.py`
- **Create:** `scripts/migrate_embeddings.py`

### Recommended Model

`BAAI/bge-base-en-v1.5` (438MB, 768 dimensions)

### Acceptance Criteria

- [ ] New model loads successfully
- [ ] Migration script works
- [ ] Retrieval quality improved

---

## Testing Checklist

- [ ] DocumentModel validation
- [ ] ChromaDB metadata storage
- [ ] Smart search with filters
- [ ] Entity search
- [ ] Embedding model loading

---

## Notes

- Phase 1 should be completed first - others depend on it
- Phase 6 is optional if time is short

---

*Assigned: January 2026*
