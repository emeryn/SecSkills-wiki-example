"""Embeddings of page chunks, computed by the worker for every new current revision.

Chunks follow headings and paragraphs, each prefixed with the page title so it stands alone.
Chunks carry the page's space for filtering, and disappear with the page (purge) or the next
revision; trashed pages are never searched.
"""

import logging
import re

from sqlalchemy.orm import Session

from app.core.context import AppContext
from app.llm.provider import LLMProvider, ProviderError
from app.models import Revision
from app.repositories import chunks as chunk_repo
from app.services import llm_config
from app.services.llm_config import LlmUnavailableError

logger = logging.getLogger(__name__)

MAX_CHARS = 1500
OVERLAP_CHARS = 200
MAX_CHUNKS_PER_PAGE = 200
BATCH_SIZE = 16
_HEADING = re.compile(r"^#{1,6}\s", re.MULTILINE)


def _split_long(paragraph: str) -> list[str]:
    pieces = []
    start = 0
    while start < len(paragraph):
        pieces.append(paragraph[start : start + MAX_CHARS])
        start += MAX_CHARS - OVERLAP_CHARS
    return pieces


def chunk(title: str, body: str) -> list[str]:
    """Pieces of at most ``MAX_CHARS`` (plus the title), split on headings then paragraphs."""
    sections = [s.strip() for s in _HEADING.split(body) if s.strip()] if body.strip() else []
    # The split drops the heading markers but keeps the heading text at the section start.
    pieces: list[str] = []
    for section in sections:
        current = ""
        for paragraph in (p.strip() for p in section.split("\n\n") if p.strip()):
            for part in _split_long(paragraph) if len(paragraph) > MAX_CHARS else [paragraph]:
                if current and len(current) + len(part) + 2 > MAX_CHARS:
                    pieces.append(current)
                    current = part
                else:
                    current = f"{current}\n\n{part}" if current else part
        if current:
            pieces.append(current)
    if not pieces:
        pieces = [""]
    return [f"# {title}\n\n{piece}".strip() for piece in pieces[:MAX_CHUNKS_PER_PAGE]]


def _embed(provider: LLMProvider, model: str, texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        vectors.extend(provider.embed(model, texts[start : start + BATCH_SIZE]))
    return vectors


def index_pending(db: Session, ctx: AppContext, limit: int = 25) -> int:
    """Index up to ``limit`` pages; returns how many were indexed (0 when disabled)."""
    try:
        config, provider = llm_config.ready(ctx)
    except LlmUnavailableError:
        return 0
    model = config.embedding_model or ""
    done = 0
    for page in chunk_repo.pages_needing_index(db, model, limit):
        revision = db.get(Revision, page.current_revision_id)
        if revision is None:
            continue
        texts = chunk(revision.title, revision.body)
        try:
            vectors = _embed(provider, model, texts)
        except ProviderError as exc:
            logger.warning("Embedding failed; will retry", extra={"error": str(exc)})
            break
        chunk_repo.replace_page_chunks(
            db, page, revision.id, model, list(zip(texts, vectors, strict=True))
        )
        db.commit()
        done += 1
    return done
