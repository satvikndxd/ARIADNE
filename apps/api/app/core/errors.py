"""Application error taxonomy.

Rules:
  * Users never see stack traces — only ``message`` + ``code`` + optional ``hint``.
  * Developer detail is logged with the request_id.
  * Every failure mode in the spec (LLM/embedding/DB/MCP/tool-args/empty
    retrieval/missing drawing/corrupt file) maps to a deterministic class.
"""
from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    code = "internal_error"
    status_code = 500

    def __init__(self, message: str, *, detail: Any = None, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail
        self.hint = hint

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"error": {"code": self.code, "message": self.message}}
        if self.hint:
            body["error"]["hint"] = self.hint
        if self.detail is not None:
            body["error"]["detail"] = self.detail
        return body


class NotFoundError(AppError):
    code = "not_found"
    status_code = 404


class ValidationError(AppError):
    code = "validation_error"
    status_code = 422


class AuthorizationError(AppError):
    code = "authorization_error"
    status_code = 403

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, hint="This action is not permitted for your role.", **kwargs)


class ConfirmationRequiredError(AppError):
    """A state-changing MCP tool was invoked without an explicit confirmation."""

    code = "confirmation_required"
    status_code = 409


class LLMUnavailableError(AppError):
    code = "llm_unavailable"
    status_code = 503

    def __init__(self, message: str = "Language model provider is unavailable.", **kw: Any) -> None:
        super().__init__(message, hint="Set DEMO_MODE=1 to run deterministic analysis offline.", **kw)


class EmbeddingError(AppError):
    code = "embedding_error"
    status_code = 503

    def __init__(self, message: str = "Embedding provider failed.", **kw: Any) -> None:
        super().__init__(message, hint="Falling back to the local deterministic embedder is automatic.", **kw)


class DatabaseError(AppError):
    code = "database_error"
    status_code = 503


class MCPError(AppError):
    code = "mcp_error"
    status_code = 502

    def __init__(self, message: str = "MCP server unreachable.", **kw: Any) -> None:
        super().__init__(message, hint="The in-process tool gateway can be used as a fallback.", **kw)


class ToolArgumentError(AppError):
    code = "tool_argument_error"
    status_code = 422


class EmptyRetrievalError(AppError):
    code = "empty_retrieval"
    status_code = 200


class DrawingNotFoundError(AppError):
    code = "drawing_not_found"
    status_code = 404


class CorruptFileError(AppError):
    code = "corrupt_file"
    status_code = 422


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.to_dict())


async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    from app.core.logging import get_logger

    get_logger("ariadne.error").exception("unhandled_exception", error_type=type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "An unexpected error occurred."}},
    )
