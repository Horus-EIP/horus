
from fastapi.testclient import TestClient
from app.main import app

def test_lifespan_events():
    # TestClient context manager triggers startup and shutdown events
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
