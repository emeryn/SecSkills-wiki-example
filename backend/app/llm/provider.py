"""Inference provider interface. Drivers normalize their errors to ``ProviderError``."""

from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Literal, Protocol

Role = Literal["system", "user", "assistant"]


class ProviderError(RuntimeError):
    """The inference server failed; ``retryable`` is true only for connection failures."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class GenerationOptions:
    temperature: float
    top_p: float
    max_tokens: int
    context_window: int


@dataclass(frozen=True)
class ModelInfo:
    name: str
    digest: str
    size_bytes: int
    format: str
    family: str


@dataclass(frozen=True)
class StreamEvent:
    """A piece of the answer, or (``done``) the final token counts."""

    text: str = ""
    done: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    extra: dict[str, int] = field(default_factory=dict)


class LLMProvider(Protocol):
    def health(self) -> str:
        """Server version or name; raises ``ProviderError``."""
        ...

    def list_models(self) -> list[ModelInfo]: ...

    def embed(self, model: str, inputs: list[str]) -> list[list[float]]: ...

    def chat_stream(
        self, model: str, messages: list[ChatMessage], options: GenerationOptions
    ) -> Generator[StreamEvent]:
        """Closing the iterator closes the upstream request."""
        ...
