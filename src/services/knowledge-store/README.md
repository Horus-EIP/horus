# Knowledge Store

> For the development team. Paths such as `tests/` and `scripts/dev/` are
> relative to the git checkout and are not part of the beta archive.

The Knowledge Store is a document storage and vector search service that serves as the memory layer for Horus AI agents. It accepts documents in multiple formats, extracts and chunks their text, generates embeddings, and stores everything in ChromaDB for fast semantic retrieval.

## Architecture

The service is a **FastAPI** application (port 8080) backed by:

- **ChromaDB** (persistent mode) for vector storage and similarity search.
- **SentenceTransformers** with the `BAAI/bge-base-en-v1.5` embedding model (768-dimensional vectors, normalized).
- **ContentAnalyzer** -- Automatic document analysis using spaCy NER, keyword-based classification, and optional LLM-powered summarization via HuggingFace transformers.
- **DocumentChunker** -- Splits every document at ingestion into passages of at most 1,000 characters, with about 200 characters of overlap, cut between sentences or lines. Each passage is one vector, so the end of a long document can be found (the embedder reads only the first 512 tokens of what it is given).
- **Prometheus** metrics at `/metrics`.
- **OpenTelemetry** instrumentation for distributed tracing.

## Supported File Types

| Format | Library           | Notes                     |
| ------ | ----------------- | ------------------------- |
| PDF    | pdfplumber        | Text-based PDF extraction |
| DOCX   | python-docx       | Microsoft Word documents  |
| Image  | pytesseract (OCR) | Scanned PDFs and images   |
| TXT    | built-in          | Plain text files          |

## API Endpoints

### Store routes (prefix: `/`)

| Method     | Path                  | Description                                       |
| ---------- | --------------------- | ------------------------------------------------- |
| `POST`   | `/`                 | Add a text document (with auto-analysis)          |
| `GET`    | `/`                 | Query by text similarity; returns passages with their chunk id and metadata |
| `DELETE` | `/{id}`             | Delete a document, its stored file and its corpus entries |
| `POST`   | `/upload`           | Upload a file, extract text, analyze, and chunk   |
| `POST`   | `/smart-search`     | Search documents with filters (category, entities); one hit per document |
| `GET`    | `/search-by-entity` | Search by entity type and value                   |
| `GET`    | `/categories`       | List all document categories with document counts |
| `GET`    | `/corpus-version`   | Version of the indexed corpus, changed by every add, delete or re-index |

### File routes (prefix: `/file`)

| Method     | Path                 | Description                                       |
| ---------- | -------------------- | ------------------------------------------------- |
| `POST`   | `/file`            | Upload multiple files (PDF, DOCX, TXT)            |
| `GET`    | `/file`            | List all indexed documents (one entry each) and metadata |
| `GET`    | `/file/resolve`    | Full text of the document(s) whose title matches a filename |
| `GET`    | `/file/{doc_id}/text` | Full text of one document, by its id          |
| `DELETE` | `/file/{filename}` | Delete a file from storage                        |
| `POST`   | `/file/{type}`     | Upload a single file by type with text conversion |

### Corpus routes (prefix: `/corpus`, `X-Corpus-Token` header required)

| Method | Path               | Description                                             |
| ------ | ------------------ | ------------------------------------------------------- |
| `POST` | `/corpus/scan`     | Index the mounted corpus folder (background job)        |
| `GET`  | `/corpus/status`   | Progress of the latest scan                             |
| `POST` | `/corpus/reindex`  | Re-index the stored documents (background job)          |
| `GET`  | `/corpus/reindex`  | Progress of the latest re-index                         |

Interactive API documentation is available at `/docs` when the server is running.

### Passages and documents

A document is stored as passages, one Chroma entry each, with the id `{doc_id}:{n}`. Every passage carries `doc_id`, `title`, `source_path` (the corpus path, empty for uploads), `chunk_index`, `char_start` and `char_end` (its place in the extracted text), `page` (PDFs only: the page it starts on), `category` and `embed_model` (the embedder that produced its vector). The first passage (`chunk_index` 0) also carries the document-level data, once: `date`, `size`, `chunk_count`, the auto-analysis (`auto_summary`, `auto_type`, entities, topics, confidence) and, for corpus files, `content_sha256`. It is written last, so a document whose first passage is missing was not stored completely: the listing ignores it and the next corpus scan stores it again.

`GET /` returns passages. Everything else works on documents: `GET /file` lists each document once, `GET /categories` counts documents, `POST /smart-search` returns each document once with its best passage (`ids` are document ids, `chunk_ids` the passages), `DELETE /{id}` removes every passage of the document, and `GET /file/resolve` and `GET /file/{doc_id}/text` rebuild the full text from the passages.

### Re-indexing existing data

Documents indexed before passages existed are stored as one whole-file entry, of which only the first 512 tokens can be found. They keep working (listed, deleted, resolved) but should be re-indexed:

```bash
python scripts/reindex-knowledge-store.py --token "$CORPUS_SCAN_TOKEN"
```

The script calls `POST /corpus/reindex` and follows `GET /corpus/reindex` until the job ends. The job splits every whole-file entry into passages (writing the passages first and removing the old entry last), and embeds again, in place, every passage whose `embed_model` is not the one the service runs. Documents already up to date are skipped, so the script is safe to run again, and a run that was interrupted continues where it stopped. Each changed document bumps the corpus version. It never runs together with a corpus scan (`409`). Changing the embedder (for example to FastEmbed) only needs a new `EMBED_MODEL` in `app/chroma_db/setup.py` for the next re-index to embed everything again; the vector size must stay 768.

### Deleting documents

`DELETE /{id}` (the trash icon in the UI) removes the Chroma entries with that ID or `doc_id` (every passage of the document), the other entries indexed from the same corpus path, and the uploaded file in `documents/` once no entry uses it. A deleted corpus file is written to `chroma_data/deleted_sources.json`, so `POST /corpus/scan` skips it (`skipped_deleted`) even after an edit. `POST /corpus/scan?include_deleted=true` indexes such files again and takes them off the list. `DELETE /file/{filename}` only removes the file on disk.

## Directory Structure

```
knowledge-store/
  requirements.txt
  app/
    main.py                 # FastAPI application setup
    __init__.py
    api/
      __init__.py           # Router registry (ROUTERS dict)
      utils.py              # File I/O helpers (save, PDF/DOCX/image extraction)
      routes/
        store.py            # Store CRUD and search endpoints
        file.py             # File upload, list, delete endpoints
    chroma_db/
      setup.py              # ChromaDB client, embedding model, collection init
      __init__.py            # Re-exports for convenience
      models/
        document.py         # DocumentModel (Pydantic)
        search.py           # SmartSearchRequest (Pydantic)
      services/
        file_service.py     # Store passages, query, document listing, delete, filters
        reindex.py          # Whole-file entries to passages, re-embedding
    services/
      content_analyzer.py   # Category, entity, topic, summary extraction
      document_chunker.py   # Passages of at most 1,000 characters, with offsets
    core/
      logging.py            # Structured JSON logging
      metrics.py            # Prometheus metric definitions
      middleware.py         # Correlation ID middleware
```

Pytest suites and client scripts: `tests/knowledge_store/` at the repository root. Dev launcher: `scripts/dev/run-knowledge-store.sh`.

## Environment Variables

The service reads environment variables directly. Defaults are suitable for local development.

| Variable                     | Description                | Default |
| ---------------------------- | -------------------------- | ------- |
| `CHROMA_TELEMETRY_ENABLED` | Disable ChromaDB telemetry | `0`   |

The embedding model (`BAAI/bge-base-en-v1.5`) is configured in `app/chroma_db/setup.py`. For deployment with other services, see `src/infra/.env.example`.

## Local Development

### Prerequisites

- Python 3.13+
- Tesseract OCR installed (for image/scanned-PDF support)

### Setup

```bash
cd src/services/knowledge-store
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_trf
```

### Run

```bash
# From repository root
bash scripts/dev/run-knowledge-store.sh
```

Or manually:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

## Running Tests

```bash
# From repository root
bash scripts/test/run-knowledge-store.sh
```

Or directly:

```bash
pytest -c tests/knowledge_store/pytest.ini tests/knowledge_store \
  --cov=src/services/knowledge-store/app --cov-report=html
```

The test suite covers store routes, file routes, content analysis, document chunking, ChromaDB setup, and utility functions.
