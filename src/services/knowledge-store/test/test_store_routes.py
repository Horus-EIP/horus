import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
from app.api.routes.store import router
from fastapi import FastAPI

app = FastAPI()
app.include_router(router)

client = TestClient(app)

def test_add_text():
    with patch("app.api.routes.store.store_file", new_callable=AsyncMock) as mock_store, \
            patch("app.api.routes.store._content_analyzer") as mock_analyzer:
        mock_analyzer.analyze.return_value = {
            "auto_category": "general",
            "auto_type": "document",
            "auto_summary": "",
            "entities": {"people": [], "companies": [], "amounts": [], "dates": []},
            "topics": [],
            "confidence_score": 0.3,
        }
        payload = {
            "id": "1",
            "title": "Test Title",
            "content": "Content test",
            "size": 10
        }

        response = client.post("/", json=payload)

        assert response.status_code == 200
        assert response.json()["status"] == "document added"
        mock_store.assert_called_once()

def test_query_no_filter():
    fake_result = {
        "documents": [["doc1"]],
        "metadatas": [[]],
        "distances": [[]]
    }

    with patch("app.api.routes.store.query_knowledge", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = fake_result

        response = client.get("/", params={"query": "test"})

        assert response.status_code == 200
        assert response.json() == fake_result

def test_query_with_filter():
    fake_result = {
        "documents": [["doc1"]],
        "metadatas": [[]],
        "distances": [[]]
    }

    with patch("app.api.routes.store.query_with_filters", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = fake_result

        response = client.get(
            "/",
            params={
                "query": "test",
                "filters": '{"title": "test"}'
            }
        )

        assert response.status_code == 200
        assert response.json() == fake_result

def test_query_no_results():
    fake_result = {"documents": [[]]}

    with patch("app.api.routes.store.query_knowledge", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = fake_result

        response = client.get("/", params={"query": "test"})

        assert response.status_code == 404

def test_delete_document():
    with patch("app.api.routes.store.delete_document", new_callable=AsyncMock) as mock_delete:
        mock_delete.return_value = {"status": "document deleted"}

        response = client.delete("/1")

        assert response.status_code == 200
        assert response.json()["status"] == "Document deleted"

MOCK_RESULTS = {
    "documents": [["doc1", "doc2"]],
    "metadatas": [[
        {
            "auto_category": "legal",
            "confidence_score": 0.95
        },
        {
            "auto_category": "legal",
            "confidence_score": 0.91
        }
    ]],
    "distances": [[0.1, 0.2]]
}

EMPTY_RESULTS = {
    "documents": [[]],
    "metadatas": [[]],
    "distances": [[]]
}

def test_smart_search_no_filters():
    with patch("app.api.routes.store.query_knowledge", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = MOCK_RESULTS

        response = client.post("/smart-search", json={"query": "worker rights"})

        assert response.status_code == 200
        mock_query.assert_called_once_with("worker rights", 5)

        body = response.json()
        assert body["query"] == "worker rights"
        assert body["filters"] is None
        assert body["total"] == 2

def test_smart_search_single_category():
    with patch("app.api.routes.store.query_with_filters", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = MOCK_RESULTS

        response = client.post("/smart-search", json={"query": "contract", "categories": ["legal"]})

        assert response.status_code == 200
        mock_query.assert_called_once_with("contract", {"auto_category": {"$eq": "legal"}}, 5)

def test_smart_search_multi_category():
    with patch("app.api.routes.store.query_with_filters", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = MOCK_RESULTS

        response = client.post("/smart-search", json={"query": "contract", "categories": ["legal", "financial"]})

        assert response.status_code == 200
        mock_query.assert_called_once_with(
            "contract",
            {"$or": [
                {"auto_category": {"$eq": "legal"}},
                {"auto_category": {"$eq": "financial"}}
            ]},
            5
        )

def test_smart_search_combined_filters():
    with patch("app.api.routes.store.query_with_filters", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = MOCK_RESULTS

        response = client.post("/smart-search", json={
            "query": "contract",
            "categories": ["legal"],
            "min_confidence": 0.9
        })

        assert response.status_code == 200
        mock_query.assert_called_once_with(
            "contract",
            {
                "$and": [
                    {"auto_category": {"$eq": "legal"}},
                    {"confidence_score": {"$gte": 0.9}}
                ]
            },
            5
        )

def test_smart_search_entity_filter():
    with patch("app.api.routes.store.query_with_filters", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = MOCK_RESULTS

        response = client.post("/smart-search", json={
            "query": "contract",
            "entities": ["Alice"]
        })

        assert response.status_code == 200
        mock_query.assert_called_once_with(
            "contract",
            {"entities_people": {"$contains": "Alice"}},
            5
        )

def test_smart_search_no_results():
    with patch("app.api.routes.store.query_knowledge", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = EMPTY_RESULTS

        response = client.post("/smart-search", json={"query": "xpto"})

        assert response.status_code == 404
        assert response.json()["detail"] == "No results found"

def test_smart_search_internal_error():
    with patch("app.api.routes.store.query_knowledge", new_callable=AsyncMock) as mock_query:
        mock_query.side_effect = Exception("ChromaDB connection failed")

        response = client.post("/smart-search", json={"query": "contract"})

        assert response.status_code == 500
        assert "ChromaDB connection failed" in response.json()["detail"]

def test_smart_search_invalid_confidence():
    response = client.post("/smart-search", json={"query": "contract", "min_confidence": 1.5})
    assert response.status_code == 422

def test_smart_search_missing_query():
    response = client.post("/smart-search", json={"categories": ["legal"]})
    assert response.status_code == 422

def test_categories_with_documents():
    fake_metadatas = [
        {"auto_category": "technical"},
        {"auto_category": "academic"},
        {"auto_category": "technical"},
        {"auto_category": ""},
    ]

    with patch("app.api.routes.store.knowledge_collection") as mock_collection:
        mock_collection.get.return_value = {"metadatas": fake_metadatas}

        response = client.get("/categories")

        assert response.status_code == 200
        body = response.json()
        assert body["total_documents"] == 4
        assert {"category": "technical", "count": 2} in body["categories"]
        assert {"category": "academic", "count": 1} in body["categories"]
        assert {"category": "uncategorized", "count": 1} in body["categories"]
        assert body["categories"][0]["count"] >= body["categories"][1]["count"]

def test_categories_empty():
    with patch("app.api.routes.store.knowledge_collection") as mock_collection:
        mock_collection.get.return_value = {"metadatas": []}

        response = client.get("/categories")

        assert response.status_code == 200
        body = response.json()
        assert body["total_documents"] == 0
        assert body["categories"] == []

def test_categories_internal_error():
    with patch("app.api.routes.store.knowledge_collection") as mock_collection:
        mock_collection.get.side_effect = Exception("ChromaDB connection failed")

        response = client.get("/categories")

        assert response.status_code == 500
        assert "ChromaDB connection failed" in response.json()["detail"]

def test_search_by_entity_people():
    with patch("app.api.routes.store.query_with_filters", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = MOCK_RESULTS

        response = client.get("/search-by-entity", params={
            "entity": "Alice",
            "entity_type": "people"
        })

        assert response.status_code == 200
        mock_query.assert_called_once_with(
            "Alice",
            {"entities_people": {"$contains": "Alice"}},
            5
        )
        body = response.json()
        assert body["entity"] == "Alice"
        assert body["entity_type"] == "people"
        assert body["total"] == 2

def test_search_by_entity_companies():
    with patch("app.api.routes.store.query_with_filters", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = MOCK_RESULTS

        response = client.get("/search-by-entity", params={
            "entity": "Acme Corp",
            "entity_type": "companies"
        })

        assert response.status_code == 200
        mock_query.assert_called_once_with(
            "Acme Corp",
            {"entities_companies": {"$contains": "Acme Corp"}},
            5
        )

def test_search_by_entity_invalid_type():
    response = client.get("/search-by-entity", params={
        "entity": "Alice",
        "entity_type": "invalid_type"
    })

    assert response.status_code == 400
    assert "Invalid entity_type" in response.json()["detail"]

def test_search_by_entity_no_results():
    with patch("app.api.routes.store.query_with_filters", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = EMPTY_RESULTS

        response = client.get("/search-by-entity", params={
            "entity": "Unknown Person",
            "entity_type": "people"
        })

        assert response.status_code == 404
        assert response.json()["detail"] == "No documents found for this entity"

def test_search_by_entity_internal_error():
    with patch("app.api.routes.store.query_with_filters", new_callable=AsyncMock) as mock_query:
        mock_query.side_effect = Exception("ChromaDB connection failed")

        response = client.get("/search-by-entity", params={
            "entity": "Alice",
            "entity_type": "people"
        })

        assert response.status_code == 500
        assert "ChromaDB connection failed" in response.json()["detail"]

def test_search_by_entity_missing_entity():
    response = client.get("/search-by-entity", params={"entity_type": "people"})
    assert response.status_code == 422

def test_search_by_entity_missing_entity_type():
    response = client.get("/search-by-entity", params={"entity": "Alice"})
    assert response.status_code == 422

def test_search_by_entity_custom_n_results():
    with patch("app.api.routes.store.query_with_filters", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = MOCK_RESULTS

        response = client.get("/search-by-entity", params={
            "entity": "Alice",
            "entity_type": "people",
            "n_results": 10
        })

        assert response.status_code == 200
        mock_query.assert_called_once_with(
            "Alice",
            {"entities_people": {"$contains": "Alice"}},
            10
        )
