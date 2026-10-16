from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.core.config import Settings
from app.core.secrets import FileSecretsProvider
from app.main import create_app


def test_health_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_reports_database_down_without_details(
    settings: Settings, secrets_provider: FileSecretsProvider
) -> None:
    broken = create_engine("postgresql+psycopg://nobody@127.0.0.1:1/none?connect_timeout=1")
    with TestClient(create_app(settings, engine=broken, secrets=secrets_provider)) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "DATABASE_UNAVAILABLE"
    assert "127.0.0.1" not in response.text
    assert error["request_id"]
