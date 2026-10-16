from collections.abc import Iterator

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.core.config import Settings
from app.core.middleware import client_ip
from app.core.secrets import FileSecretsProvider
from app.main import create_app


@pytest.fixture
def upload_client(
    settings: Settings, engine: Engine, secrets_provider: FileSecretsProvider
) -> Iterator[TestClient]:
    app = create_app(settings, engine=engine, secrets=secrets_provider)

    @app.post("/api/v1/test/body")
    async def body(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    with TestClient(
        app, base_url="https://testserver", headers={"X-Requested-With": "XMLHttpRequest"}
    ) as client:
        yield client


def test_request_id_generated_and_returned(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert len(response.headers["x-request-id"]) == 32


def test_valid_upstream_request_id_is_kept(client: TestClient) -> None:
    upstream = "0123456789abcdef0123456789abcdef"
    response = client.get("/api/v1/health", headers={"X-Request-ID": upstream})
    assert response.headers["x-request-id"] == upstream


def test_malformed_upstream_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "bad\tid"})
    assert response.headers["x-request-id"] != "bad\tid"


def test_api_responses_are_not_cached(client: TestClient) -> None:
    assert client.get("/api/v1/health").headers["cache-control"] == "no-store"


def test_body_within_limit_is_accepted(upload_client: TestClient) -> None:
    assert upload_client.post("/api/v1/test/body", content=b"x" * 100).json() == {"size": 100}


def test_body_over_limit_by_content_length_returns_413(upload_client: TestClient) -> None:
    response = upload_client.post("/api/v1/test/body", content=b"x" * 10_000)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_body_over_limit_when_chunked_returns_413(upload_client: TestClient) -> None:
    def chunks() -> Iterator[bytes]:
        for _ in range(10):
            yield b"x" * 1000

    response = upload_client.post("/api/v1/test/body", content=chunks())
    assert response.status_code == 413


@pytest.mark.parametrize(
    ("peer", "forwarded", "count", "expected"),
    [
        ("10.0.0.2", "203.0.113.7", 1, "203.0.113.7"),
        ("10.0.0.2", "198.51.100.1, 203.0.113.7", 1, "203.0.113.7"),
        ("10.0.0.2", "198.51.100.1, 203.0.113.7", 2, "198.51.100.1"),
        ("10.0.0.2", "203.0.113.7", 0, "10.0.0.2"),
        ("10.0.0.2", "not-an-ip", 1, "10.0.0.2"),
        ("10.0.0.2", None, 1, "10.0.0.2"),
        ("10.0.0.2", "203.0.113.7", 2, "10.0.0.2"),
    ],
)
def test_client_ip_trusts_only_configured_hops(
    peer: str, forwarded: str | None, count: int, expected: str
) -> None:
    assert client_ip(peer, forwarded, count) == expected
