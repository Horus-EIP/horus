import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_health_check(async_client):
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "knowledge-store"

@pytest.mark.asyncio
async def test_metrics_endpoint(async_client):
    # Try with trailing slash as mount might force it or client handling
    # If using Starlette mounts, usually prefix matches.
    # But checking for either to be robust against configuration.
    response = await async_client.get("/metrics/")
    if response.status_code == 404:
         response = await async_client.get("/metrics")
    
    # If 405 occurs, it means method not allowed, which usually implies path matched but method wrong.
    # We assert 200.
    assert response.status_code == 200
    assert "knowledge_store_system_info" in response.text

# ...

@pytest.mark.asyncio
async def test_http_exception_handler(async_client):
    # Use a multi-segment path to avoid matching /{id} (which causes 405 DELETE)
    response = await async_client.get("/non/existent/route")
    assert response.status_code == 404
