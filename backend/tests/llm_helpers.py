"""A fake inference server: deterministic embeddings, scripted streamed answers."""

import hashlib
import json
import math
import re
from collections.abc import Generator
from typing import Any

from fastapi.testclient import TestClient

from app.core.context import AppContext
from app.llm.provider import ChatMessage, GenerationOptions, ModelInfo, ProviderError, StreamEvent
from tests.sso_helpers import configure

CHAT = "llama3.1:8b"
EMBED = "nomic-embed-text:latest"
DIMENSIONS = 32


def embed_text(text: str) -> list[float]:
    """Bag of words hashed into a small vector: similar texts get similar vectors."""
    vector = [0.001] * DIMENSIONS
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        bucket = int(hashlib.sha256(word.encode()).hexdigest(), 16) % DIMENSIONS
        vector[bucket] += 1.0
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector]


class FakeLLM:
    def __init__(self) -> None:
        self.models = [
            ModelInfo(CHAT, "sha256:chat-1", 4_000_000_000, "gguf", "llama"),
            ModelInfo(EMBED, "sha256:embed-1", 270_000_000, "gguf", "nomic-bert"),
        ]
        self.answer = ["The checklist", " is in [1]."]
        self.requests: list[list[ChatMessage]] = []
        self.fail_before_first = 0
        self.fail_after_first = False
        self.closed = 0

    def health(self) -> str:
        return "0.12.0"

    def list_models(self) -> list[ModelInfo]:
        return self.models

    def embed(self, model: str, inputs: list[str]) -> list[list[float]]:
        return [embed_text(text) for text in inputs]

    def chat_stream(
        self, model: str, messages: list[ChatMessage], options: GenerationOptions
    ) -> Generator[StreamEvent]:
        self.requests.append(messages)
        try:
            if self.fail_before_first:
                self.fail_before_first -= 1
                raise ProviderError("connection refused", retryable=True)
            for index, text in enumerate(self.answer):
                if self.fail_after_first and index == 1:
                    raise ProviderError("connection reset", retryable=True)
                yield StreamEvent(text=text)
            yield StreamEvent(done=True, prompt_tokens=120, completion_tokens=8)
        finally:
            self.closed += 1


def enable(ctx: AppContext, **overrides: Any) -> None:
    configure(
        ctx,
        "llm",
        enabled=True,
        url="https://llm.example.com",
        chat_model=CHAT,
        embedding_model=EMBED,
        model_digests={CHAT: "sha256:chat-1", EMBED: "sha256:embed-1"},
        **overrides,
    )


def events(response: Any) -> list[tuple[str, Any]]:
    """Parse a server-sent events body into ``(event, data)`` pairs."""
    parsed = []
    for block in response.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        parsed.append((lines["event"], json.loads(lines["data"])))
    return parsed


def ask(client: TestClient, question: str, **body: Any) -> Any:
    return client.post("/api/v1/ask", json={"question": question, **body})
