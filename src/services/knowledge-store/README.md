# Knowledge Store

> For the development team. Paths such as `tests/` and `scripts/dev/` are
> relative to the git checkout and are not part of the beta archive.

The Knowledge Store is a document storage and vector search service that serves as the memory layer for Horus AI agents. It accepts documents in multiple formats, extracts and chunks their text, generates embeddings, and stores everything in ChromaDB for fast semantic retrieval.

## Architecture

The service is a **FastAPI** application (port 8080) backed by:

- **ChromaDB** (persistent mode) for vector storage and similarity search.
- **SentenceTransformers** with the `BAAI/bge-base-en-v1.5` embedding model (768-dimensional vectors, normalized).
- **ContentAnalyzer** -- Automatic document analysis using spaCy NER, keyword-based classification, and optional LLM-powered summarization via HuggingFace transformers.
- **DocumentChunker** -- Splits large documents into smaller overlapping chunks for granular retrieval.
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
| `GET`    | `/`                 | Query the knowledge store by text similarity      |
| `DELETE` | `/{id}`             | Delete a document, its stored file and its corpus entries |
| `POST`   | `/upload`           | Upload a file, extract text, analyze, and chunk   |
| `POST`   | `/smart-search`     | Search with metadata filters (category, entities) |
| `GET`    | `/search-by-entity` | Search by entity type and value                   |
| `GET`    | `/categories`       | List all document categories with counts          |

### File routes (prefix: `/file`)

| Method     | Path                 | Description                                       |
| ---------- | -------------------- | ------------------------------------------------- |
| `POST`   | `/file`            | Upload multiple files (PDF, DOCX, TXT)            |
| `GET`    | `/file`            | List all indexed files and metadata               |
| `DELETE` | `/file/{filename}` | Delete a file from storage                        |
| `POST`   | `/file/{type}`     | Upload a single file by type with text conversion |

Interactive API documentation is available at `/docs` when the server is running.

### Deleting documents

`DELETE /{id}` (the trash icon in the UI) removes the Chroma entries with that ID or `doc_id`, the other entries indexed from the same corpus path, and the uploaded file in `documents/` once no entry uses it. A deleted corpus file is written to `chroma_data/deleted_sources.json`, so `POST /corpus/scan` skips it (`skipped_deleted`) even after an edit. `POST /corpus/scan?include_deleted=true` indexes such files again and takes them off the list. `DELETE /file/{filename}` only removes the file on disk.

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
        file_service.py     # Store, query, delete, filter logic
    services/
      content_analyzer.py   # Category, entity, topic, summary extraction
      document_chunker.py   # Text chunking with overlap
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
