"""Minimal MCP server: JSON-RPC 2.0 over Streamable HTTP (stateless, JSON responses).

Supported: ``initialize``, ``ping``, ``tools/list``, ``tools/call`` and notifications. Each tool
declares the key scope it needs and whether it is destructive (then ``confirm: true`` is required).
Tools run through the same services, validation and permission checks as the REST API, with the
key owner's rights narrowed by the key's scopes. Every tool call is audited: key, tool, masked
arguments, outcome and duration.
"""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.context import AppContext
from app.core.errors import AppError
from app.models import ApiKey, User
from app.schemas.common import StrictModel
from app.services import audit_service
from app.services.audit_service import Actor

logger = logging.getLogger("app.mcp")

SUPPORTED_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
SERVER_VERSION = "0.1.0"
MAX_ARGUMENT_TEXT = 80
# Arguments whose content is never written to the audit trail, only its size.
CONTENT_ARGUMENTS = frozenset({"body", "content", "query"})

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602


@dataclass(frozen=True)
class ToolContext:
    db: Session
    ctx: AppContext
    user: User
    key: ApiKey
    actor: Actor


class ToolError(Exception):
    """A tool failed; the code and message are returned to the client (``isError``)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ConfirmArgs(StrictModel):
    """Destructive tools: the client must pass ``confirm: true`` explicitly."""

    confirm: bool = False


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    arguments: type[StrictModel]
    scope: str
    run: Callable[[ToolContext, Any], dict[str, Any]]
    destructive: bool = False

    def definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.arguments.model_json_schema(),
            "annotations": {
                "readOnlyHint": self.scope.endswith(":read"),
                "destructiveHint": self.destructive,
            },
        }


class RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _mask(value: Any, name: str = "") -> Any:
    if isinstance(value, dict):
        return {k: _mask(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(v) for v in value[:20]]
    if isinstance(value, str) and (name in CONTENT_ARGUMENTS or len(value) > MAX_ARGUMENT_TEXT):
        return f"<{len(value)} characters>"
    return value


def _call_tool(
    tools: dict[str, Tool], context: ToolContext, params: dict[str, Any], endpoint: str
) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    tool = tools.get(name) if isinstance(name, str) else None
    started = time.monotonic()
    outcome, code = "success", None
    try:
        if tool is None:
            raise RpcError(INVALID_PARAMS, f"Unknown tool: {str(name)[:100]}")
        if not isinstance(arguments, dict):
            raise RpcError(INVALID_PARAMS, "Arguments must be an object")
        if tool.scope not in context.key.scopes:
            raise ToolError("FORBIDDEN", f"This key lacks the {tool.scope} scope")
        try:
            parsed = tool.arguments.model_validate(arguments)
        except ValidationError as exc:
            fields = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
            raise ToolError("INVALID_ARGUMENTS", f"Invalid arguments: {', '.join(fields)}") from exc
        if tool.destructive and not getattr(parsed, "confirm", False):
            raise ToolError(
                "CONFIRMATION_REQUIRED", "Destructive tool: call it again with confirm=true"
            )
        try:
            result = tool.run(context, parsed)
        except AppError as exc:
            context.db.rollback()
            raise ToolError(exc.code, exc.message) from exc
        return {
            "content": [{"type": "text", "text": json.dumps(result, default=str)}],
            "structuredContent": result,
            "isError": False,
        }
    except ToolError as exc:
        outcome, code = "failure", exc.code
        return {
            "content": [{"type": "text", "text": f"{exc.code}: {exc.message}"}],
            "isError": True,
        }
    except RpcError:
        outcome, code = "failure", "UNKNOWN_TOOL" if tool is None else "INVALID_PARAMS"
        raise
    finally:
        duration = round((time.monotonic() - started) * 1000)
        audit_service.record(
            context.db,
            context.actor,
            "mcp.tool_call",
            outcome=outcome,
            target_type="api_key",
            target_id=context.key.id,
            after={
                "endpoint": endpoint,
                "tool": str(name)[:100],
                "arguments": _mask(arguments) if isinstance(arguments, dict) else None,
                "error": code,
                "duration_ms": duration,
            },
        )
        context.db.commit()


def _initialize(params: dict[str, Any], instructions: str) -> dict[str, Any]:
    requested = params.get("protocolVersion")
    version = requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": "wiki", "version": SERVER_VERSION},
        "instructions": instructions,
    }


def handle(
    message: Any,
    tools: dict[str, Tool],
    context: ToolContext,
    endpoint: str,
    instructions: str,
) -> dict[str, Any] | None:
    """One JSON-RPC message; returns the response, or None for notifications and responses."""
    request_id = message.get("id") if isinstance(message, dict) else None
    try:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            raise RpcError(INVALID_REQUEST, "Expected a single JSON-RPC 2.0 message")
        method = message.get("method")
        if "id" not in message:
            return None
        params = message.get("params") or {}
        if not isinstance(params, dict):
            raise RpcError(INVALID_PARAMS, "params must be an object")
        if method == "initialize":
            result = _initialize(params, instructions)
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": [tool.definition() for tool in tools.values()]}
        elif method == "tools/call":
            result = _call_tool(tools, context, params, endpoint)
        else:
            raise RpcError(METHOD_NOT_FOUND, f"Method not found: {str(method)[:100]}")
    except RpcError as exc:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": exc.code, "message": exc.message},
        }
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def registry(*tools: Tool) -> dict[str, Tool]:
    return {tool.name: tool for tool in tools}
