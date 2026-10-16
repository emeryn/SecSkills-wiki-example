"""Ollama driver and LLM settings: no tools sent, cancel closes the connection, SSRF on URLs."""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.context import AppContext
from app.core.outbound_url import Destination
from app.llm import ollama
from app.llm.ollama import OllamaProvider
from app.llm.provider import ChatMessage, GenerationOptions
from app.services import llm_config, rag_indexer
from tests.helpers import make_user, sign_in, write
from tests.llm_helpers import CHAT, EMBED, FakeLLM

OPTIONS = GenerationOptions(temperature=0.2, top_p=0.9, max_tokens=256, context_window=4096)
BASE = Destination(host="llm.example.com", port=443, address="93.184.216.34", path="/ollama")


def test_chat_payload_never_offers_tools_and_close_cancels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: dict[str, Any] = {}
    closed: list[bool] = []

    def fake_stream(destination: Destination, method: str, **kwargs: Any) -> Iterator[bytes]:
        sent.update(path=destination.path, payload=json.loads(kwargs["body"]))
        try:
            yield b'{"message": {"content": "Hel"}, "done": false}\n'
            yield b'{"message": {"content": "lo"}, "done": false}\n'
            yield b'{"done": true, "prompt_eval_count": 10, "eval_count": 2}\n'
        finally:
            closed.append(True)

    monkeypatch.setattr(ollama, "stream_lines", fake_stream)
    provider = OllamaProvider(BASE, scheme="https", api_key="k")
    stream = provider.chat_stream(CHAT, [ChatMessage("user", "hi")], OPTIONS)
    assert next(stream).text == "Hel"
    stream.close()
    assert closed == [True]
    assert sent["path"] == "/ollama/api/chat"
    assert "tools" not in sent["payload"]
    assert sent["payload"]["options"]["num_predict"] == 256


def test_chunks_follow_headings_and_carry_the_title() -> None:
    pieces = rag_indexer.chunk("Runbook", "Intro.\n\n## Rollback\n\nUndo." + "\n\nx" * 2000)
    assert all(piece.startswith("# Runbook") for piece in pieces)
    assert all(len(piece) <= rag_indexer.MAX_CHARS + 20 for piece in pieces)
    assert rag_indexer.chunk("Empty", "") == ["# Empty"]


@pytest.fixture
def admin(client: TestClient, ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    fake = FakeLLM()
    llm_config.clear_cache()
    monkeypatch.setattr(llm_config, "make_provider", lambda ctx, config: fake)
    sign_in(client, make_user(ctx, "root", role="admin"))
    return client


def _save(admin: TestClient, **values: Any) -> Any:
    body = {"enabled": True, "chat_model": CHAT, "embedding_model": EMBED, **values}
    return write(admin, "PUT", "/api/v1/admin/settings/llm", json=body)


@pytest.mark.parametrize(
    "url",
    [
        "https://169.254.169.254",
        "http://127.0.0.1:11434",
        "http://93.184.216.34:11434",
        "http://10.0.0.5:11434",
        "https://[::1]:11434",
        "ftp://10.0.0.5",
    ],
)
def test_unsafe_inference_urls_are_refused(admin: TestClient, url: str) -> None:
    assert _save(admin, url=url).status_code == 422


def test_private_http_server_needs_an_allowlisted_network(admin: TestClient) -> None:
    allow = write(
        admin,
        "PUT",
        "/api/v1/admin/settings/security",
        json={"allowed_private_networks": ["10.0.0.0/8"]},
    )
    assert allow.status_code == 200
    saved = _save(admin, url="http://10.0.0.5:11434", api_key="token-0123456789-abcd")
    assert saved.status_code == 200, saved.text
    values = saved.json()["values"]
    assert values["model_digests"] == {CHAT: "sha256:chat-1", EMBED: "sha256:embed-1"}
    assert values["api_key"] == "••••abcd"


def test_digests_cannot_be_set_by_the_client(admin: TestClient) -> None:
    saved = _save(admin, url="https://93.184.216.34", model_digests={CHAT: "sha256:forged"})
    assert saved.json()["values"]["model_digests"][CHAT] == "sha256:chat-1"


def test_unknown_or_unsafe_model_format_is_refused(
    admin: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeLLM()
    fake.models[0] = fake.models[0].__class__(CHAT, "sha256:x", 1, "pickle", "llama")
    monkeypatch.setattr(llm_config, "make_provider", lambda ctx, config: fake)
    assert _save(admin, url="https://93.184.216.34").status_code == 422
    assert _save(admin, url="https://93.184.216.34", chat_model="missing:1").status_code == 422


def test_model_discovery_marks_approved_models(admin: TestClient) -> None:
    _save(admin, url="https://93.184.216.34")
    models = admin.get("/api/v1/admin/llm/models").json()
    assert {(m["name"], m["approved"]) for m in models} == {(CHAT, True), (EMBED, True)}
