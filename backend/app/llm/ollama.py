"""Ollama driver: ``/api/version``, ``/api/tags``, ``/api/embed``, ``/api/chat`` (NDJSON stream).

Every request goes through the SSRF-checked, pinned HTTP client. No tools are ever sent.
"""

import json
from collections.abc import Generator
from dataclasses import replace
from typing import Any

from app.core.outbound_http import (
    HttpStatusError,
    OutboundHttpError,
    Scheme,
    request,
    stream_lines,
)
from app.core.outbound_url import Destination
from app.llm.provider import (
    ChatMessage,
    GenerationOptions,
    ModelInfo,
    ProviderError,
    StreamEvent,
)

REQUEST_TIMEOUT_SECONDS = 30.0
# CPU inference can take a while before the first token, and between tokens.
STREAM_TIMEOUT_SECONDS = 120.0
EMBED_TIMEOUT_SECONDS = 120.0


def _error_message(body: bytes) -> str:
    try:
        value = json.loads(body)
    except ValueError:
        return "invalid response"
    error = value.get("error") if isinstance(value, dict) else None
    return str(error)[:200] if error else "error"


class OllamaProvider:
    def __init__(
        self,
        base: Destination,
        *,
        scheme: Scheme,
        ca_pem: str | None = None,
        api_key: str | None = None,
        proxy: Destination | None = None,
    ) -> None:
        self._base = base
        self._scheme = scheme
        self._ca_pem = ca_pem
        self._proxy = proxy
        self._headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"

    def _at(self, path: str) -> Destination:
        return replace(self._base, path=self._base.path.rstrip("/") + path)

    def _json(self, path: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
        body = json.dumps(payload).encode() if payload is not None else None
        try:
            response = request(
                self._at(path),
                "POST" if payload is not None else "GET",
                body=body,
                headers=self._headers,
                ca_pem=self._ca_pem,
                scheme=self._scheme,
                proxy=self._proxy,
                timeout=timeout,
            )
        except OutboundHttpError as exc:
            raise ProviderError(str(exc), retryable=True) from exc
        if response.status != 200:  # noqa: PLR2004
            raise ProviderError(
                f"Inference server error {response.status}: {_error_message(response.body)}"
            )
        try:
            value = json.loads(response.body)
        except ValueError as exc:
            raise ProviderError("The inference server answered something that is not JSON") from exc
        if not isinstance(value, dict):
            raise ProviderError("Unexpected answer from the inference server")
        return value

    def health(self) -> str:
        return str(self._json("/api/version", None, REQUEST_TIMEOUT_SECONDS).get("version", "?"))

    def list_models(self) -> list[ModelInfo]:
        models = self._json("/api/tags", None, REQUEST_TIMEOUT_SECONDS).get("models")
        found = []
        for item in models if isinstance(models, list) else []:
            if not isinstance(item, dict):
                continue
            raw_details = item.get("details")
            details: dict[str, Any] = raw_details if isinstance(raw_details, dict) else {}
            found.append(
                ModelInfo(
                    name=str(item.get("name", "")),
                    digest=str(item.get("digest", "")),
                    size_bytes=int(item.get("size") or 0),
                    format=str(details.get("format", "")),
                    family=str(details.get("family", "")),
                )
            )
        return found

    def embed(self, model: str, inputs: list[str]) -> list[list[float]]:
        value = self._json("/api/embed", {"model": model, "input": inputs}, EMBED_TIMEOUT_SECONDS)
        embeddings = value.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(inputs):
            raise ProviderError("The inference server returned no embeddings")
        return [[float(x) for x in vector] for vector in embeddings]

    def chat_stream(
        self, model: str, messages: list[ChatMessage], options: GenerationOptions
    ) -> Generator[StreamEvent]:
        payload = {
            "model": model,
            "stream": True,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "options": {
                "temperature": options.temperature,
                "top_p": options.top_p,
                "num_predict": options.max_tokens,
                "num_ctx": options.context_window,
            },
        }
        lines = stream_lines(
            self._at("/api/chat"),
            "POST",
            body=json.dumps(payload).encode(),
            headers=self._headers,
            ca_pem=self._ca_pem,
            scheme=self._scheme,
            proxy=self._proxy,
            timeout=STREAM_TIMEOUT_SECONDS,
        )
        try:
            for line in lines:
                event = self._event(line)
                if event is not None:
                    yield event
                    if event.done:
                        return
        except HttpStatusError as exc:
            raise ProviderError(
                f"Inference server error {exc.status}: {_error_message(exc.body)}"
            ) from exc
        except OutboundHttpError as exc:
            raise ProviderError(str(exc), retryable=True) from exc
        finally:
            lines.close()

    @staticmethod
    def _event(line: bytes) -> StreamEvent | None:
        try:
            value = json.loads(line)
        except ValueError as exc:
            raise ProviderError("Malformed stream from the inference server") from exc
        if not isinstance(value, dict):
            return None
        if value.get("error"):
            raise ProviderError(f"Inference server error: {str(value['error'])[:200]}")
        raw_message = value.get("message")
        message: dict[str, Any] = raw_message if isinstance(raw_message, dict) else {}
        if value.get("done"):
            return StreamEvent(
                text=str(message.get("content") or ""),
                done=True,
                prompt_tokens=int(value.get("prompt_eval_count") or 0),
                completion_tokens=int(value.get("eval_count") or 0),
            )
        text = message.get("content")
        return StreamEvent(text=str(text)) if text else None
