from collections.abc import Iterator

import pytest
from fastapi import Query
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.core.config import Settings
from app.core.secrets import FileSecretsProvider
from app.main import create_app


@pytest.fixture
def routes_client(
    settings: Settings, engine: Engine, secrets_provider: FileSecretsProvider
) -> Iterator[TestClient]:
    app = create_app(settings, engine=engine, secrets=secrets_provider)

    @app.get("/api/v1/test/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    @app.get("/api/v1/test/echo")
    def echo(limit: int = Query(le=100)) -> dict[str, int]:
        return {"limit": limit}

    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as client:
        yield client


def test_unknown_route_uses_error_format(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


def test_forced_500_has_no_stack_trace(routes_client: TestClient) -> None:
    response = routes_client.get("/api/v1/test/boom")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert body["error"]["request_id"] == response.headers["x-request-id"]
    assert "secret internal detail" not in response.text
    assert "Traceback" not in response.text


def test_validation_error_does_not_echo_input(routes_client: TestClient) -> None:
    response = routes_client.get("/api/v1/test/echo", params={"limit": "<script>9999</script>"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "<script>" not in response.text
