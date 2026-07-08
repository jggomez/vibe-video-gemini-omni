"""Integration tests for FastAPI HTTP endpoints."""

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health_endpoint():
    """Verify liveness probe endpoint."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "Vibe Video Studio"


def test_video_placeholder_endpoint():
    """Verify video artifact fallback serving."""
    response = client.get("/api/videos/non_existent_video.mp4")
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert len(response.content) > 0
