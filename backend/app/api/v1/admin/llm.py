"""Ask the wiki administration: model discovery and the versioned system prompt."""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import Ctx, CurrentActor, Db, require
from app.core.errors import AppError
from app.core.permissions import Permission
from app.llm.provider import ProviderError
from app.models import User
from app.schemas.common import StrictModel
from app.services import llm_config, prompt_service
from app.services.llm_config import LlmUnavailableError

router = APIRouter(prefix="/llm", tags=["admin"])

manage = require(Permission.SETTINGS_MANAGE)
manage_recent = require(Permission.SETTINGS_MANAGE, recent=True)


class ModelOut(BaseModel):
    name: str
    digest: str
    size_bytes: int
    format: str
    family: str
    approved: bool


class PromptVersion(BaseModel):
    id: int
    content: str
    is_default: bool
    created_by: str | None
    created_at: datetime


class PromptOut(BaseModel):
    current: str
    default: str
    versions: list[PromptVersion]


class PromptUpdate(StrictModel):
    content: str = Field(min_length=1, max_length=20000)


@router.get("/models", dependencies=[Depends(manage)])
def list_models(ctx: Ctx) -> list[ModelOut]:
    config = ctx.runtime.snapshot().llm
    if not config.url:
        raise AppError(409, "NOT_ENABLED", "Save the inference server URL first")
    try:
        provider = llm_config.make_provider(ctx, config)
        models = llm_config.models(provider, config.url, fresh=True)
    except (LlmUnavailableError, ProviderError) as exc:
        raise AppError(503, "LLM_UNAVAILABLE", "The inference server is unavailable") from exc
    return [
        ModelOut(
            name=m.name,
            digest=m.digest,
            size_bytes=m.size_bytes,
            format=m.format,
            family=m.family,
            approved=config.model_digests.get(m.name) == m.digest,
        )
        for m in models
    ]


def _prompt_out(db: Db) -> PromptOut:
    versions = prompt_service.history(db)
    names = dict(
        db.execute(
            select(User.id, User.username).where(
                User.id.in_([v.created_by for v in versions if v.created_by])
            )
        ).all()
    )
    return PromptOut(
        current=prompt_service.text(db),
        default=prompt_service.default(),
        versions=[
            PromptVersion(
                id=v.id,
                content=v.content,
                is_default=v.is_default,
                created_by=names.get(v.created_by) if v.created_by else None,
                created_at=v.created_at,
            )
            for v in versions
        ],
    )


@router.get("/prompt", dependencies=[Depends(manage)])
def get_prompt(db: Db) -> PromptOut:
    return _prompt_out(db)


@router.put("/prompt", dependencies=[Depends(manage_recent)])
def put_prompt(body: PromptUpdate, db: Db, actor: CurrentActor) -> PromptOut:
    prompt_service.update(db, actor, body.content)
    return _prompt_out(db)


@router.delete("/prompt", dependencies=[Depends(manage_recent)])
def reset_prompt(db: Db, actor: CurrentActor) -> PromptOut:
    """Back to the factory prompt (a new version: history is kept)."""
    prompt_service.reset(db, actor)
    return _prompt_out(db)
