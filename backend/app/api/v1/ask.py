"""Ask the wiki: questions answered from the pages the user can read, streamed as SSE."""

from collections.abc import AsyncIterator
from typing import Literal

import anyio.to_thread
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import Ctx, CurrentPrincipal, Db, authenticated
from app.llm.provider import ChatMessage
from app.schemas.common import StrictModel
from app.services import ask_service

router = APIRouter(prefix="/ask", tags=["ask"])


class HistoryMessage(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class AskRequest(StrictModel):
    question: str = Field(min_length=1, max_length=2000)
    # Earlier turns of this conversation, kept by the browser only.
    history: list[HistoryMessage] = Field(default_factory=list, max_length=6)


class AskStatus(BaseModel):
    enabled: bool
    daily_token_quota: int
    tokens_used_today: int


@router.get("/status", dependencies=[Depends(authenticated)])
def status(principal: CurrentPrincipal, db: Db, ctx: Ctx) -> AskStatus:
    config = ctx.runtime.snapshot().llm
    usage = ask_service.usage_today(db, principal.user.id)
    return AskStatus(
        enabled=config.enabled,
        daily_token_quota=config.daily_token_quota,
        tokens_used_today=(usage.prompt_tokens + usage.completion_tokens) if usage else 0,
    )


@router.post("", dependencies=[Depends(authenticated)])
def ask(body: AskRequest, principal: CurrentPrincipal, db: Db, ctx: Ctx) -> StreamingResponse:
    """Errors before the answer starts are normal JSON errors (503, 429); later ones are events."""
    history = [ChatMessage(m.role, m.content) for m in body.history]
    prepared = ask_service.prepare(db, ctx, principal.user.id, body.question.strip(), history)
    events = ask_service.stream(ctx, prepared, principal.user.id)

    async def body_stream() -> AsyncIterator[str]:
        try:
            while (chunk := await anyio.to_thread.run_sync(next, events, None)) is not None:
                yield chunk
        finally:
            # Client gone or answer finished: closing the generator closes the upstream request.
            await anyio.to_thread.run_sync(events.close)

    return StreamingResponse(
        body_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
