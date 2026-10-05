# Knowledge Store

> For the development team. Paths such as `tests/` and `scripts/dev/` are
> relative to the git checkout and are not part of the beta archive.

The Knowledge Store is a document storage and vector search service that serves as the memory layer for Horus AI agents. It accepts documents in multiple formats, extracts and chunks their text, generates embeddings, and stores everything in ChromaDB for fast semantic retrieval.

## Architecture

The service is a **FastAPI** application (port 8080) backed by:

- **ChromaDB** (persistent mode) for vector storage and similarity search.
- **FastEmbed** (ONNX Runtime, no torch) with the `BAAI/bge-base-en-v1.5` embedding model (768-dimensional vectors, normalized). A question is embedded with the BGE query prefix (`Represent this sentence for searching relevant passages: `), added once by the service: FastEmbed's own query path adds none. Passages are embedded without it.
- **ContentAnalyzer** -- Automatic document analysis using spaCy NER (`en_core_web_trf` when installed, else `en_core_web_sm`, else regex only), keyword-based classification, and optional LLM-powered summarization via HuggingFace transformers (GPU image only).
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
| `GET`    | `/file/resolve`    | Full text of the document(s) whose title matches a filename; `documents` lists each match's `doc_id`, `title` and `text` so an answer can cite the one it used |
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

Documents indexed before passages existed are stored as one whole-file entry, of which only the first 512 tokens can be found, and passages written before FastEmbed carry `embed_model` `sentence-transformers:BAAI/bge-base-en-v1.5`. Both keep working (listed, deleted, resolved, found) and are re-indexed once, by one job:

- **At startup**, the service compares every stored entry with the running embedder. When it finds whole-file entries or passages with another `embed_model`, it logs `startup: re-index <job> started in the background for <n> documents ...` and starts the re-index job (`trigger: startup` in `GET /corpus/reindex`). `/health` and every other route answer while it runs; `POST /corpus/scan` answers `409` until it ends. When nothing needs it, it logs `startup: every stored passage is embedded with <embed_model>`. `KNOWLEDGE_STORE_REINDEX_ON_STARTUP=0` turns the job off and only logs how many documents need it.
- **By hand**, for example after the startup job was turned off or failed:

```bash
python scripts/reindex-knowledge-store.py --token "$CORPUS_SCAN_TOKEN"
```

The script calls `POST /corpus/reindex` and follows `GET /corpus/reindex` until the job ends. The job splits every whole-file entry into passages (writing the passages first and removing the old entry last), and embeds again, in place, every passage whose `embed_model` is not the one the service runs. Documents already up to date are skipped, so the job is safe to run again, and a run that was interrupted continues where it stopped. Each changed document bumps the corpus version. It never runs together with a corpus scan (`409`). A job that ends with no failure writes the embedder into the collection metadata.

`embed_model` names the runtime, its version and the model, for example `fastembed-0.8.1:BAAI/bge-base-en-v1.5`, so upgrading FastEmbed re-embeds everything once at the next start. The collection metadata records the same: `embedding_model` (`BAAI/bge-base-en-v1.5`), `embed_model`, `embedding_runtime` (`fastembed`), `embedding_runtime_version` and `dimensions` (768). Changing the model only needs a new `MODEL_NAME` in `app/chroma_db/setup.py`; the vector size must stay 768.

The move from sentence-transformers to FastEmbed alone would not need a re-index: `scripts/compare-embeddings.py` embeds the demo corpus, chunked like the service chunks it, and the eval and router questions with both setups and reports the cosine similarity of each pair of vectors (re-index below 0.99). Measured on 2026-10-05 (AMD Ryzen AI 9 HX 370, Windows 11, 336 texts): BGE minimum 0.999989, mean 0.999993, the same top passage for all 84 graded eval questions; MiniLM minimum 1.000000. The startup job still re-embeds the old passages once, because their `embed_model` differs, and splits whole-file entries in the same pass.

### Deleting documents

`DELETE /{id}` (the trash icon in the UI) removes the Chroma entries with that ID or `doc_id` (every passage of the document), the other entries indexed from the same corpus path, and the uploaded file in `documents/` once no entry uses it. A deleted corpus file is written to `chroma_data/deleted_sources.json`, so `POST /corpus/scan` skips it (`skipped_deleted`) even after an edit. `POST /corpus/scan?include_deleted=true` indexes such files again and takes them off the list. `DELETE /file/{filename}` only removes the file on disk.

## Directory Structure

```
knowledge-store/
  requirements.txt          # CPU image: FastEmbed, no torch
  requirements-gpu.txt      # GPU image: requirements.txt plus torch, transformers, en_core_web_trf
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
| `KNOWLEDGE_STORE_EMBED_DEVICE` | `auto` (CUDA when onnxruntime offers it), `cpu`, or `cuda` (falls back to CPU with a warning when onnxruntime has no CUDA provider; the images ship the CPU onnxruntime) | `auto` |
| `KNOWLEDGE_STORE_EMBED_THREADS` | Threads of the embedder's ONNX Runtime session; unset or not a positive number leaves the choice to onnxruntime | unset |
| `KNOWLEDGE_STORE_REINDEX_ON_STARTUP` | `0`, `false`, `no` or `off` keeps the startup re-index from running; it then only logs how many documents need one | on |
| `FASTEMBED_CACHE_PATH` | Where FastEmbed keeps the ONNX model. The image sets `/app/.cache/fastembed` and downloads the model there at build time | FastEmbed's default (a temp folder) |

The embedding model (`BAAI/bge-base-en-v1.5`) is configured in `app/chroma_db/setup.py`. For deployment with other services, see `src/infra/.env.example`.

### CPU and GPU images

The Dockerfile installs `requirements.txt` when the build argument `TORCH_INDEX_URL` is the CPU wheel index (`https://download.pytorch.org/whl/cpu`, set by `docker-compose.cpu.yml`): a CPU image has FastEmbed and `en_core_web_sm`, and no torch, transformers or sentence-transformers. Any other index (the default `https://pypi.org/simple`) builds the GPU image from `requirements-gpu.txt`, which installs the pinned torch from that index first, then `requirements.txt`, transformers and `en_core_web_trf` for the content analyzer's optional pipelines. CI (`cpu-images` job, `scripts/ci/check-cpu-image.py`) fails when torch or sentence-transformers shows up in a CPU image.

### Metrics

Besides query and embedding latency, `/metrics` exposes `knowledge_store_document_operations_total{operation,status}` (`add` for every stored document, `delete` for every `DELETE /{id}`, `get` for `GET /file/{doc_id}/text` and `GET /file/resolve`; `status` is `success` or `error`, a document that is not found counts as `error`) and `knowledge_store_documents_total`, the number of documents stored as passages, set at startup, after every add or delete and when a re-index ends. A document still stored as one whole-file entry is counted once the re-index has split it.

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
