"""System prompts: factory defaults in ``app/llm/prompts/*.md``, edits stored as versions.

The newest version is used. Resetting adds a version with the factory text (history is kept).
"""

import hashlib
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LlmPrompt
from app.services import audit_service
from app.services.audit_service import Actor

ANSWER = "answer"
PROMPTS_DIR = Path(__file__).resolve().parents[1] / "llm" / "prompts"
HISTORY_SIZE = 20


@cache
def default(name: str = ANSWER) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def current(db: Session, name: str = ANSWER) -> LlmPrompt | None:
    return db.scalar(
        select(LlmPrompt).where(LlmPrompt.name == name).order_by(LlmPrompt.id.desc()).limit(1)
    )


def text(db: Session, name: str = ANSWER) -> str:
    row = current(db, name)
    return row.content if row is not None else default(name)


def history(db: Session, name: str = ANSWER) -> list[LlmPrompt]:
    return list(
        db.scalars(
            select(LlmPrompt)
            .where(LlmPrompt.name == name)
            .order_by(LlmPrompt.id.desc())
            .limit(HISTORY_SIZE)
        ).all()
    )


def _fingerprint(content: str) -> dict[str, object]:
    return {"sha256": hashlib.sha256(content.encode()).hexdigest()[:16], "length": len(content)}


def _add(db: Session, actor: Actor, content: str, *, is_default: bool, action: str) -> LlmPrompt:
    before = text(db)
    row = LlmPrompt(
        name=ANSWER,
        content=content,
        is_default=is_default,
        created_by=actor.user_id,
        created_at=datetime.now(UTC),
    )
    db.add(row)
    db.flush()
    audit_service.record(
        db,
        actor,
        action,
        target_type="llm_prompt",
        target_id=ANSWER,
        before=_fingerprint(before),
        after={**_fingerprint(content), "version": row.id},
    )
    db.commit()
    return row


def update(db: Session, actor: Actor, content: str) -> LlmPrompt:
    return _add(db, actor, content.strip(), is_default=False, action="llm.prompt_updated")


def reset(db: Session, actor: Actor) -> LlmPrompt:
    return _add(db, actor, default(), is_default=True, action="llm.prompt_reset")
