import pytest
import sys
from fastapi.testclient import TestClient
from fastapi import FastAPI
import chromadb
from unittest.mock import patch

_has_ephemeral = hasattr(chromadb, "EphemeralClient")
_has_client = hasattr(chromadb, "Client")
_skip_reason = "chromadb in-memory client not available (Python 3.14+ / version mismatch)"

@pytest.fixture(scope="function")
def test_app():
    if _has_ephemeral:
        test_client = chromadb.EphemeralClient()
    elif _has_client:
        test_client = chromadb.Client()
    else:
        pytest.skip(_skip_reason)
    test_collection = test_client.get_or_create_collection("test_knowledge")

    with patch("app.chroma_db.knowledge_collection", test_collection), \
         patch("app.chroma_db.services.file_service.knowledge_collection", test_collection), \
         patch("app.api.routes.store.knowledge_collection", test_collection):

        from app.api.routes.store import router
        app = FastAPI()
        app.include_router(router)
        yield TestClient(app), test_collection

    test_client.delete_collection("test_knowledge")

def test_store_and_smart_search_no_filters(test_app):
    client, _ = test_app

    client.post("/", json={
        "id": "doc-1",
        "title": "Ethseer Docker Guide",
        "content": "How to setup docker compose for ethereum blockchain explorer with caddy proxy",
        "size": 100,
        "auto_category": "technical",
        "confidence_score": 0.95
    })

    response = client.post("/smart-search", json={"query": "docker ethereum", "n_results": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert any("docker" in doc.lower() or "ethereum" in doc.lower()
               for doc in body["results"]["documents"])

def test_store_and_smart_search_category_filter(test_app):
    client, _ = test_app

    client.post("/", json={
        "id": "doc-1",
        "title": "Ethseer Docker Guide",
        "content": "How to setup docker compose for ethereum blockchain",
        "size": 100,
        "auto_category": "technical",
        "confidence_score": 0.95
    })
    client.post("/", json={
        "id": "doc-2",
        "title": "Family Business Syllabus",
        "content": "Succession planning and family enterprise governance",
        "size": 100,
        "auto_category": "academic",
        "confidence_score": 0.90
    })

    response = client.post("/smart-search", json={
        "query": "docker",
        "categories": ["technical"],
        "n_results": 5
    })

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["results"]["metadatas"][0]["auto_category"] == "technical"

def test_store_and_smart_search_confidence_filter(test_app):
    client, _ = test_app

    client.post("/", json={
        "id": "doc-1",
        "title": "High Confidence Doc",
        "content": "Important technical document about APIs",
        "size": 100,
        "auto_category": "technical",
        "confidence_score": 0.95
    })
    client.post("/", json={
        "id": "doc-2",
        "title": "Low Confidence Doc",
        "content": "Some technical document about APIs",
        "size": 100,
        "auto_category": "technical",
        "confidence_score": 0.50
    })

    response = client.post("/smart-search", json={
        "query": "technical document",
        "min_confidence": 0.90,
        "n_results": 5
    })

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["results"]["metadatas"][0]["confidence_score"] >= 0.90

def test_store_and_search_by_entity(test_app):
    client, _ = test_app

    client.post("/", json={
        "id": "doc-1",
        "title": "Legal Contract",
        "content": "Contract between Alice and Bob",
        "size": 100,
        "auto_category": "legal",
        "confidence_score": 0.95,
        "entities": {
            "people": ["Alice", "Bob"]
        }
    })

    response = client.get("/search-by-entity", params={
        "entity": "Alice",
        "entity_type": "people"
    })

    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert body["entity"] == "Alice"

def test_store_and_categories(test_app):
    client, _ = test_app

    client.post("/", json={"id": "doc-1", "title": "T1", "content": "technical doc", "size": 10, "auto_category": "technical", "confidence_score": 0.9})
    client.post("/", json={"id": "doc-2", "title": "T2", "content": "technical doc 2", "size": 10, "auto_category": "technical", "confidence_score": 0.9})
    client.post("/", json={"id": "doc-3", "title": "A1", "content": "academic doc", "size": 10, "auto_category": "academic", "confidence_score": 0.9})

    response = client.get("/categories")

    assert response.status_code == 200
    body = response.json()
    assert body["total_documents"] == 3
    assert body["categories"][0] == {"category": "technical", "count": 2}
    assert body["categories"][1] == {"category": "academic", "count": 1}

def test_smart_search_no_results(test_app):
    client, _ = test_app

    response = client.post("/smart-search", json={"query": "dnsljdnasjdnkasjdkdansld", "n_results": 5})

    assert response.status_code == 404