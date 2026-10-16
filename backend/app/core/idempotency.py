"""Idempotency store for state-changing requests of signed-in users.

Same key and same request: the stored response is replayed. Same key, different request: 422.
A request still running under the same key: 409. Server errors are not stored, so they can be
retried. Endpoints that issue or rotate session cookies are excluded: a replayed response
cannot carry the cookie.
"""

import hashlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from app.core.csrf import session_cookie
from app.core.errors import error_body
from app.core.middleware import ASGIApp, Message, Receive, Scope, Send, header, send_json
from app.core.security import token_hash
from app.models import IdempotencyKey
from app.repositories import sessions as session_repo

TTL = timedelta(hours=24)
MAX_STORED_BODY = 1024 * 1024
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# "Ask the wiki" streams its answer (nothing to replay) and changes no data.
EXCLUDED_PREFIXES = ("/api/v1/auth/", "/api/v1/me/password", "/api/v1/me/mfa", "/api/v1/ask")


class IdempotencyMiddleware:
    def __init__(self, app: ASGIApp, sessions: sessionmaker[Session]) -> None:
        self.app = app
        self.sessions = sessions

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path: str = scope.get("path", "")
        if (
            scope["type"] != "http"
            or scope["method"] not in WRITE_METHODS
            or not path.startswith("/api/")
            or path.startswith(EXCLUDED_PREFIXES)
        ):
            await self.app(scope, receive, send)
            return
        cookie = session_cookie(scope)
        user_id = await run_in_threadpool(self._user_id, cookie) if cookie else None
        if user_id is None:
            await self.app(scope, receive, send)
            return

        raw_key = header(scope, b"idempotency-key")
        try:
            key = uuid.UUID(raw_key or "")
        except ValueError:
            await send_json(
                send, 428, error_body("IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header required")
            )
            return

        body = await _read_body(receive)
        digest = hashlib.sha256(
            b"\x00".join(
                [scope["method"].encode(), path.encode(), scope.get("query_string", b""), body]
            )
        ).digest()
        outcome = await run_in_threadpool(self._claim, user_id, key, digest)
        if outcome is not None:
            await outcome(send)
            return

        captured: dict[str, Any] = {"status": 500, "headers": [], "body": bytearray()}

        async def replay_receive() -> Message:
            nonlocal body
            chunk, body = body, b""
            return {"type": "http.request", "body": chunk, "more_body": False}

        async def capture_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                captured["status"] = message["status"]
                captured["headers"] = message.get("headers", [])
            elif message["type"] == "http.response.body":
                captured["body"].extend(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, replay_receive, capture_send)
        finally:
            await run_in_threadpool(self._complete, user_id, key, captured)

    def _user_id(self, cookie: str) -> uuid.UUID | None:
        with self.sessions() as db:
            found = session_repo.find_valid(db, token_hash(cookie), datetime.now(UTC))
            return found.user_id if found is not None and found.state == "active" else None

    def _claim(
        self, user_id: uuid.UUID, key: uuid.UUID, digest: bytes
    ) -> Callable[[Send], Any] | None:
        now = datetime.now(UTC)
        with self.sessions() as db:
            db.execute(
                delete(IdempotencyKey).where(
                    IdempotencyKey.user_id == user_id,
                    IdempotencyKey.key == key,
                    IdempotencyKey.expires_at <= now,
                )
            )
            inserted = db.execute(
                insert(IdempotencyKey)
                .values(user_id=user_id, key=key, request_hash=digest, expires_at=now + TTL)
                .on_conflict_do_nothing()
                .returning(IdempotencyKey.key)
            ).first()
            db.commit()
            if inserted is not None:
                return None
            row = db.scalar(
                select(IdempotencyKey).where(
                    IdempotencyKey.user_id == user_id, IdempotencyKey.key == key
                )
            )
        if row is None or row.request_hash != digest:
            return lambda send: send_json(
                send,
                422,
                error_body("IDEMPOTENCY_KEY_REUSED", "Key already used for another request"),
            )
        if row.status_code is None:
            return lambda send: send_json(
                send, 409, error_body("REQUEST_IN_PROGRESS", "Request is still being processed")
            )
        return lambda send: _replay(send, row)

    def _complete(self, user_id: uuid.UUID, key: uuid.UUID, captured: dict[str, Any]) -> None:
        status: int = captured["status"]
        body = bytes(captured["body"])
        where = (IdempotencyKey.user_id == user_id, IdempotencyKey.key == key)
        with self.sessions() as db:
            if status >= 500 or len(body) > MAX_STORED_BODY:  # noqa: PLR2004
                db.execute(delete(IdempotencyKey).where(*where))
            else:
                content_type = next(
                    (v.decode() for k, v in captured["headers"] if k == b"content-type"), None
                )
                db.execute(
                    update(IdempotencyKey)
                    .where(*where)
                    .values(status_code=status, content_type=content_type, response_body=body)
                )
            db.commit()


async def _read_body(receive: Receive) -> bytes:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            return b"".join(chunks)


async def _replay(send: Send, row: IdempotencyKey) -> None:
    body = row.response_body or b""
    headers = [(b"content-length", str(len(body)).encode()), (b"idempotent-replayed", b"true")]
    if row.content_type:
        headers.append((b"content-type", row.content_type.encode()))
    await send({"type": "http.response.start", "status": row.status_code, "headers": headers})
    await send({"type": "http.response.body", "body": body})
