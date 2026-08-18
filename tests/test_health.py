from fastapi.testclient import TestClient

from app.core.database import get_db
from app.main import app

client = TestClient(app)


def test_health_endpoint():
    """
    Test GET /api/v1/health returns HTTP 200 and status ok.
    """
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_db_health_endpoint_mock_success():
    """
    Test GET /api/v1/health/db when database execution succeeds.
    """
    class DummyDB:
        def execute(self, statement):
            return True

    app.dependency_overrides[get_db] = lambda: DummyDB()
    try:
        response = client.get("/api/v1/health/db")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "connected"}
    finally:
        app.dependency_overrides.clear()


def test_db_health_endpoint_mock_failure():
    """
    Test GET /api/v1/health/db when database execution fails.
    """
    class FailingDB:
        def execute(self, statement):
            raise Exception("Connection refused")

    app.dependency_overrides[get_db] = lambda: FailingDB()
    try:
        response = client.get("/api/v1/health/db")
        assert response.status_code == 503
        data = response.json()
        assert data["detail"]["status"] == "error"
        assert data["detail"]["database"] == "disconnected"
    finally:
        app.dependency_overrides.clear()
