# Horus Knowledge Store API Reference

Vector database and document retrieval service.

**Base URL (Docker Compose default):** `http://<host>:8080` — see service `knowledge_store` in `src/infra/docker-compose.yml` (repository root).

**Path layout:** Store routes are mounted at the application root (`POST /`, `GET /`, and paths such as `/smart-search`). File routes are under `/file/...`. The FastAPI app sets `root_path="/api/knowledge-store"` for use behind a reverse proxy; when you call the container directly on port 8080, use the paths above without an extra prefix unless your gateway adds one.

Prometheus metrics are exposed at **`GET /metrics`** (no trailing slash required).

The service uses ChromaDB with the `BAAI/bge-base-en-v1.5` embedding model (see `main.py`).

Authentication is not enforced on these endpoints in the default configuration (treat the service as internal to the Docker network).

---

## Table of Contents

- [Health](#health)
- [Store Operations](#store-operations)
- [File Operations](#file-operations)

---

## Health

### GET /health

Return service health status.

**Auth:** None

**Response:** `200 OK`

```json
{
  "status": "healthy",
  "service": "knowledge-store"
}
```

---

## Store Operations

### POST /

Add a plain text document to the knowledge store. Automatic content analysis is performed (category detection, entity extraction, topic identification, summarization).

**Auth:** None (internal service)

**Request Body:** `application/json`

| Field              | Type     | Required | Description                                |
|--------------------|----------|----------|--------------------------------------------|
| id                 | string   | Yes      | Unique document identifier                 |
| title              | string   | Yes      | Document title                             |
| content            | string   | Yes      | Full text content                          |
| size               | integer  | Yes      | Content size in bytes                      |
| auto_category      | string   | No       | Category override (default: auto-detected) |
| auto_type          | string   | No       | Document type override                     |
| auto_summary       | string   | No       | Summary override                           |
| entities           | object   | No       | Pre-extracted entities (people, companies, amounts, dates) |
| topics             | string[] | No       | Topic keywords                             |
| confidence_score   | float    | No       | Analysis confidence 0--1 (default: `0.0`)  |
| user_category      | string   | No       | User-assigned category                     |
| user_tags          | string[] | No       | User-assigned tags                         |
| is_chunk           | boolean  | No       | Whether this is a chunk of a larger document |
| parent_id          | string   | No       | Parent document ID when `is_chunk` is true |

**Response:** `200 OK`

```json
{
  "status": "document added",
  "id": "123456",
  "auto_analysis": {
    "category": "finance",
    "entities": {
      "people": ["John Doe"],
      "companies": ["Acme Corp"],
      "amounts": ["$1,000,000"],
      "dates": ["2025-01-15"]
    },
    "topics": ["revenue", "growth"],
    "summary": "Quarterly financial results showing growth..."
  }
}
```

---

### GET /

Query the knowledge store for relevant documents using semantic search with optional metadata filters.

**Auth:** None (internal service)

**Query Parameters:**

| Parameter | Type    | Required | Description                                          |
|-----------|---------|----------|------------------------------------------------------|
| query     | string  | Yes      | Search query text                                    |
| n_results | integer | No       | Number of results to return (default: `1`)           |
| filters   | string  | No       | JSON string with ChromaDB where-clause filters       |

**Response:** `200 OK`

```json
{
  "ids": [["id1", "id2"]],
  "distances": [[0.1, 0.2]],
  "metadatas": [[
    { "title": "Doc 1" },
    { "title": "Doc 2" }
  ]],
  "documents": [[
    "Content 1",
    "Content 2"
  ]]
}
```

**Errors:**

- `400` -- Invalid filters JSON format
- `404` -- No results found
- `500` -- Query execution failure

---

### DELETE /{id}

Remove a document from the knowledge store by its ID.

**Auth:** None (internal service)

**Path Parameters:**

| Parameter | Type   | Description               |
|-----------|--------|---------------------------|
| id        | string | Unique document identifier |

**Response:** `200 OK`

```json
{
  "status": "Document deleted"
}
```

**Errors:**

- `404` -- Document not found or deletion failed

---

### POST /smart-search

Perform an advanced search with metadata filters including category, entities, and confidence score.

**Auth:** None (internal service)

**Request Body:** `application/json`

| Field          | Type     | Required | Description                                      |
|----------------|----------|----------|--------------------------------------------------|
| query          | string   | Yes      | Search query text                                |
| n_results      | integer  | No       | Max results to return (1--50, default: `5`)      |
| categories     | string[] | No       | Filter by document categories                    |
| entities       | string[] | No       | Filter by entity names                           |
| min_confidence | float    | No       | Minimum confidence score filter (0.0--1.0)       |
| entity_type    | string   | No       | Filter by entity type (e.g., `people`)           |

**Response:** `200 OK`

```json
{
  "query": "financial report",
  "filters": { "auto_category": "finance" },
  "total": 3,
  "results": {
    "documents": ["Content 1", "Content 2", "Content 3"],
    "metadatas": [
      { "title": "Q1 Report", "auto_category": "finance" },
      { "title": "Q2 Report", "auto_category": "finance" },
      { "title": "Annual Summary", "auto_category": "finance" }
    ],
    "distances": [0.12, 0.18, 0.25]
  }
}
```

**Errors:**

- `404` -- No results found or no results within distance threshold
- `500` -- Search execution failure

---

### GET /search-by-entity

Search for documents containing a specific named entity.

**Auth:** None (internal service)

**Query Parameters:**

| Parameter   | Type    | Required | Description                                               |
|-------------|---------|----------|-----------------------------------------------------------|
| entity      | string  | Yes      | Entity value to search for (e.g., a person's name)       |
| entity_type | string  | Yes      | One of: `people`, `companies`, `amounts`, `dates`        |
| n_results   | integer | No       | Max results to return (default: `5`)                     |

**Response:** `200 OK`

```json
{
  "entity": "John Doe",
  "entity_type": "people",
  "filter": { "entities_people": { "$contains": "John Doe" } },
  "total": 2,
  "results": {
    "ids": [["id1", "id2"]],
    "documents": [["Doc content 1", "Doc content 2"]],
    "metadatas": [[{ "title": "Contract A" }, { "title": "Report B" }]],
    "distances": [[0.05, 0.12]]
  }
}
```

**Errors:**

- `400` -- Invalid entity_type (must be one of: `people`, `companies`, `amounts`, `dates`)
- `404` -- No documents found for this entity
- `500` -- Search execution failure

---

### GET /categories

Get all document categories in the knowledge store with document counts.

**Auth:** None (internal service)

**Response:** `200 OK`

```json
{
  "total_documents": 42,
  "categories": [
    { "category": "finance", "count": 15 },
    { "category": "technical", "count": 12 },
    { "category": "legal", "count": 8 },
    { "category": "uncategorized", "count": 7 }
  ]
}
```

Categories are sorted by count in descending order.

**Errors:**

- `500` -- Retrieval failure

---

### POST /upload

Upload a file (PDF, DOCX, TXT), extract its text content, run auto-analysis, and chunk the text for storage.

**Auth:** None (internal service)

**Request Body:** `multipart/form-data`

| Field | Type | Required | Description                               |
|-------|------|----------|-------------------------------------------|
| file  | file | Yes      | File to upload (PDF, DOCX, TXT supported) |

**Response:** `200 OK`

```json
{
  "filename": "example.pdf",
  "auto_analysis": {
    "topics": ["AI", "Technology"],
    "summary": "An example document about AI..."
  },
  "chunks": [
    "Chunk 1 content...",
    "Chunk 2 content..."
  ],
  "total_chunks": 2
}
```

**Errors:**

- `400` -- File processing error (unsupported format, corrupt file, etc.)

---

## File Operations

### POST /file

Upload multiple files to the knowledge store. Each file is saved to disk, text is extracted, auto-analysis is performed, and the document is indexed in ChromaDB.

**Auth:** None (internal service)

**Request Body:** `multipart/form-data`

| Field | Type   | Required | Description                                    |
|-------|--------|----------|------------------------------------------------|
| files | file[] | Yes      | One or more files (PDF, DOCX, TXT supported)  |

**Response:** `200 OK`

Returns a list of results, one per file. Failed files include an `error` field instead of success fields.

```json
[
  {
    "filename": "doc.pdf",
    "doc_id": "a1b2c3d4e5f6",
    "stored_at": "/path/to/doc.pdf",
    "auto_analysis": {
      "category": "finance",
      "topics": ["revenue"],
      "summary": "Financial report..."
    }
  },
  {
    "filename": "corrupt.pdf",
    "error": "Unable to extract text from PDF"
  }
]
```

---

### GET /file

List all files currently indexed in the knowledge store with their metadata.

**Auth:** None (internal service)

**Response:** `200 OK`

```json
{
  "documents": [
    {
      "id": "123",
      "title": "doc.pdf",
      "content": "Full text content of the document...",
      "date": "2025-01-01",
      "size": 1024
    }
  ]
}
```

**Errors:**

- `404` -- Error retrieving files from the store

---

### DELETE /file/{filename}

Delete a file from the physical storage by its filename. Searches the `documents` directory recursively.

**Auth:** None (internal service)

**Path Parameters:**

| Parameter | Type   | Description           |
|-----------|--------|-----------------------|
| filename  | string | Name of the file      |

**Response:** `200 OK`

```json
{
  "msg": "doc.pdf deleted"
}
```

**Errors:**

- `404` -- File not found

---

### POST /file/{type}

Upload a single file specifying its type explicitly, convert to text, analyze, and store. Supports type-specific conversion pipelines.

**Auth:** None (internal service)

**Path Parameters:**

| Parameter | Type   | Description                                   |
|-----------|--------|-----------------------------------------------|
| type      | string | File type: `pdf`, `docx`, or `image`          |

**Query Parameters:**

| Parameter | Type   | Required | Description                  |
|-----------|--------|----------|------------------------------|
| doc_id    | string | Yes      | Pre-assigned document ID     |

**Request Body:** `multipart/form-data`

| Field | Type | Required | Description          |
|-------|------|----------|----------------------|
| file  | file | Yes      | File to upload       |

**Response:** `200 OK`

```json
{
  "filename": "document.pdf",
  "stored_at": "/path/to/document.pdf",
  "text": "Extracted text content...",
  "auto_analysis": {
    "category": "legal",
    "topics": ["contract", "terms"],
    "summary": "Legal contract document..."
  }
}
```

**Errors:**

- `400` -- Invalid file type (must be `pdf`, `docx`, or `image`)
