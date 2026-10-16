"""Inference server from the LLM settings: SSRF-checked destination, pinned model digests.

Models are approved when the settings are saved: their digest (as listed by the server) is pinned,
and a model whose digest changes afterwards is refused until an administrator saves again.
Only GGUF and safetensors models are accepted (never pickle-based formats).
"""

import ipaddress
import logging
import threading
import time
from collections.abc import Callable
from urllib.parse import urlsplit

from app.core.context import AppContext
from app.core.outbound_url import (
    Destination,
    Network,
    OutboundUrlError,
    parse_networks,
    resolve,
)
from app.llm.ollama import OllamaProvider
from app.llm.provider import LLMProvider, ModelInfo, ProviderError
from app.schemas.settings import LlmSettings

logger = logging.getLogger(__name__)

MODEL_CACHE_SECONDS = 60.0
ACCEPTED_FORMATS = frozenset({"gguf", "safetensors"})


class LlmUnavailableError(Exception):
    """Ask the wiki cannot run; ``code`` is the API error code, ``message`` is safe to show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _allowed(ctx: AppContext) -> list[Network]:
    try:
        return parse_networks(ctx.runtime.snapshot().security.allowed_private_networks)
    except OutboundUrlError:
        return []


def destination(config: LlmSettings, allowed: list[Network]) -> tuple[Destination, str]:
    """``(destination, scheme)``; plain http only to an allowlisted private address."""
    parts = urlsplit(config.url or "")
    scheme = parts.scheme
    port = parts.port or (443 if scheme == "https" else 80)
    target = resolve(parts.hostname or "", port, allowed, path=parts.path or "/")
    if scheme == "http":
        address = ipaddress.ip_address(target.address)
        if address.is_global or not any(address in network for network in allowed):
            raise OutboundUrlError(
                "Plain http is only allowed towards an allowlisted private network; use https"
            )
    return target, scheme


def proxy_destination(config: LlmSettings, allowed: list[Network]) -> Destination | None:
    if not config.proxy_url:
        return None
    parts = urlsplit(config.proxy_url)
    return resolve(parts.hostname or "", parts.port or 3128, allowed)


def build_provider(ctx: AppContext, config: LlmSettings) -> LLMProvider:
    allowed = _allowed(ctx)
    try:
        target, scheme = destination(config, allowed)
        proxy = proxy_destination(config, allowed)
    except OutboundUrlError as exc:
        raise LlmUnavailableError("LLM_UNAVAILABLE", exc.reason) from exc
    return OllamaProvider(
        target,
        scheme="http" if scheme == "http" else "https",
        ca_pem=config.ca_pem,
        api_key=config.api_key,
        proxy=proxy,
    )


ProviderFactory = Callable[[AppContext, LlmSettings], LLMProvider]
# Replaced in tests by a fake inference server.
make_provider: ProviderFactory = build_provider

_cache_lock = threading.Lock()
_model_cache: dict[str, tuple[float, list[ModelInfo]]] = {}


def clear_cache() -> None:
    with _cache_lock:
        _model_cache.clear()


def models(provider: LLMProvider, key: str, *, fresh: bool = False) -> list[ModelInfo]:
    with _cache_lock:
        cached = _model_cache.get(key)
    if not fresh and cached is not None and time.monotonic() - cached[0] < MODEL_CACHE_SECONDS:
        return cached[1]
    found = provider.list_models()
    with _cache_lock:
        _model_cache[key] = (time.monotonic(), found)
    return found


def pin(provider: LLMProvider, config: LlmSettings) -> dict[str, str]:
    """Digests of the chosen models; raises ``ValueError`` with a reason to show."""
    available = {model.name: model for model in models(provider, config.url or "", fresh=True)}
    pins: dict[str, str] = {}
    for name in (config.chat_model, config.embedding_model):
        if name is None:
            continue
        model = available.get(name)
        if model is None:
            raise ValueError(f"The inference server has no model named {name}")
        if model.format.lower() not in ACCEPTED_FORMATS:
            raise ValueError(f"{name}: only GGUF and safetensors models are accepted")
        pins[name] = model.digest
    return pins


def ready(ctx: AppContext) -> tuple[LlmSettings, LLMProvider]:
    """Enabled settings and a provider whose models still match their pinned digests."""
    config = ctx.runtime.snapshot().llm
    if not config.enabled or not config.chat_model or not config.embedding_model:
        raise LlmUnavailableError("LLM_DISABLED", "Ask the wiki is not enabled")
    provider = make_provider(ctx, config)
    try:
        available = {m.name: m for m in models(provider, config.url or "")}
    except ProviderError as exc:
        raise LlmUnavailableError("LLM_UNAVAILABLE", "The inference server is unavailable") from exc
    for name in (config.chat_model, config.embedding_model):
        model = available.get(name)
        if model is None or config.model_digests.get(name) != model.digest:
            logger.error("Inference model missing or changed since approval", extra={"model": name})
            raise LlmUnavailableError(
                "LLM_MODEL_CHANGED",
                "The approved model changed on the inference server; "
                "an administrator must review it",
            )
    return config, provider
