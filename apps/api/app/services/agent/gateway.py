"""Tool gateway: authorization → confirmation → transport → audit.

Transport selection is explicit and recorded:

* ``mcp-http``              — the TypeScript MCP server (official SDK) executed
  the tool over streamable HTTP;
* ``in-process``            — DEMO/offline path executing the identical handler
  inside the API process;
* ``in-process-fallback``   — MCP was configured but unreachable; the fallback
  is logged and shown in the audit trail, never silent.

Security order (never reversed): role authorization → confirmation check for
mutating tools → argument validation → execution.
"""
from __future__ import annotations

import asyncio
import threading
from contextlib import AsyncExitStack
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError, AuthorizationError, ConfirmationRequiredError
from app.core.ids import new_id
from app.core.logging import Timer, get_logger
from app.core.security import Principal, authorize_tool, is_mutating_tool
from app.db.models import Confirmation, ToolExecution
from app.services.agent.tools import TOOL_BY_NAME
from app.services.audit import record

log = get_logger(__name__)

_mcp_state: dict[str, Any] = {"healthy": None, "checked_at": 0.0}


@dataclass
class ToolResult:
    ok: bool
    tool: str
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    error_code: str | None = None
    status: str = "ok"  # ok | error | denied | pending_confirmation
    transport: str = "in-process"
    latency_ms: float = 0.0
    execution_id: str = ""
    mutating: bool = False


def payload_digest(tool: str, args: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({"tool": tool, "args": args}, sort_keys=True, default=str).encode()).hexdigest()


def mcp_healthy(timeout: float = 1.2) -> bool:
    if not settings.mcp_enabled:
        return False
    now = time.time()
    if _mcp_state["healthy"] is not None and now - _mcp_state["checked_at"] < 20:
        return bool(_mcp_state["healthy"])
    import httpx

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(settings.mcp_server_url.rsplit("/mcp", 1)[0] + "/health")
            ok = resp.status_code == 200
    except Exception:
        ok = False
    _mcp_state.update(healthy=ok, checked_at=now)
    return ok


class _McpSessionPool:
    """One long-lived MCP client session on a private event-loop thread.

    Opening a streamable-HTTP MCP session costs a full initialize handshake;
    doing that per tool call added seconds of latency, so the session is kept
    alive and calls are dispatched thread-safely.  Any failure poisons the
    pool for ``cooldown`` seconds and the gateway falls back in-process.
    """

    def __init__(self, cooldown: float = 20.0) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session = None
        self._lock = threading.Lock()
        self._cooldown = cooldown
        self._broken_until = 0.0

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(target=self._loop.run_forever,
                                                name="ariadne-mcp-client", daemon=True)
                self._thread.start()
            return self._loop

    async def _connect(self) -> Any:
        try:
            from mcp.client.streamable_http import streamable_http_client as _connect
        except ImportError:  # mcp SDK 1.x
            from mcp.client.streamable_http import streamablehttp_client as _connect  # type: ignore[attr-defined]
        try:
            from mcp import ClientSession
        except ImportError:  # pragma: no cover
            from mcp.client.session import ClientSession  # type: ignore[no-redef]
        stack = AsyncExitStack()
        streams = await stack.enter_async_context(_connect(settings.mcp_server_url))
        session = await stack.enter_async_context(ClientSession(streams[0], streams[1]))
        await session.initialize()
        self._stack = stack
        return session

    def call(self, tool: str, payload: dict, timeout: float = 5.0) -> dict:
        if time.time() < self._broken_until:
            raise AppError("MCP pool cooling down", detail={"tool": tool})
        loop = self._ensure_loop()
        try:
            fut = asyncio.run_coroutine_threadsafe(self._call(tool, payload), loop)
            return fut.result(timeout=timeout)
        except Exception as exc:
            self._broken_until = time.time() + self._cooldown
            self._reset()
            raise AppError(f"MCP call failed: {exc}", detail={"tool": tool}) from exc

    async def _call(self, tool: str, payload: dict) -> dict:
        if self._session is None:
            log.info("mcp_pool_connecting", url=settings.mcp_server_url)
            self._session = await self._connect()
            log.info("mcp_pool_connected")
        res = await self._session.call_tool(tool, payload)
        is_error = bool(getattr(res, "is_error", getattr(res, "isError", False)))
        texts = [c.text for c in (res.content or []) if getattr(c, "text", None)]
        if is_error:
            raise AppError(texts[0] if texts else "mcp error", detail={"tool": tool})
        return json.loads(texts[0]) if texts else {}

    def _reset(self) -> None:
        stack = getattr(self, "_stack", None)
        session = self._session
        self._session = None
        loop = self._loop
        if loop and (stack or session):
            async def _close() -> None:
                try:
                    if session is not None:
                        await session.close() if hasattr(session, "close") else None
                except Exception:  # noqa: BLE001
                    pass
                try:
                    if stack is not None:
                        await stack.aclose()
                except Exception:  # noqa: BLE001
                    pass
            try:
                asyncio.run_coroutine_threadsafe(_close(), loop).result(timeout=5)
            except Exception:  # noqa: BLE001
                pass


_mcp_pool = _McpSessionPool()


def _call_mcp(tool: str, args: dict, principal: Principal, confirmation_id: str | None) -> dict:
    """Execute through the real MCP server (official SDK, streamable HTTP)."""
    payload = dict(args)
    payload["_context"] = {
        "user_id": principal.user_id,
        "role": principal.role.value,
        "confirmation_id": confirmation_id,
    }
    return _mcp_pool.call(tool, payload)


class ToolGateway:
    def __init__(self, session: Session) -> None:
        self.session = session

    def execute(
        self,
        tool_name: str,
        args: dict[str, Any],
        principal: Principal,
        *,
        confirmation_id: str | None = None,
        run_id: str | None = None,
        chat_session_id: str | None = None,
        force_transport: str | None = None,
        transport_label: str | None = None,
    ) -> ToolResult:
        spec = TOOL_BY_NAME.get(tool_name)
        mutating = is_mutating_tool(tool_name)
        if spec is None:
            return self._finish(
                ToolResult(ok=False, tool=tool_name, status="error", mutating=mutating,
                           error=f"Unknown tool '{tool_name}'.", error_code="unknown_tool"),
                principal, args, run_id, chat_session_id,
            )

        # 1 — authorization (deterministic, server-side)
        try:
            authorize_tool(principal.role, tool_name)
        except AuthorizationError as exc:
            record(self.session, principal=principal, action="tool.denied", tool=tool_name,
                   arguments=args, result_summary=exc.message, severity="warning", analysis_id=run_id)
            return self._finish(
                ToolResult(ok=False, tool=tool_name, status="denied", mutating=mutating,
                           error=exc.message, error_code=exc.code),
                principal, args, run_id, chat_session_id,
            )

        # 2 — confirmation gate for mutating tools
        if mutating:
            gate_error = self._check_confirmation(tool_name, args, confirmation_id)
            if gate_error is not None:
                return self._finish(gate_error, principal, args, run_id, chat_session_id)

        # 3 — argument validation
        try:
            validated = spec.validate(args)
        except AppError as exc:
            return self._finish(
                ToolResult(ok=False, tool=tool_name, status="error", mutating=mutating,
                           error=exc.message, error_code=exc.code,
                           result={"detail": exc.detail}),
                principal, args, run_id, chat_session_id,
            )

        # 4 — transport
        transport = force_transport or ("mcp-http" if mcp_healthy() else
                                        ("in-process-fallback" if settings.mcp_enabled else "in-process"))
        with Timer() as t:
            try:
                if transport == "mcp-http":
                    try:
                        result = _call_mcp(tool_name, args, principal, confirmation_id)
                    except Exception as exc:  # MCP down mid-flight → fallback
                        log.warning("mcp_call_failed_using_fallback", tool=tool_name, error=str(exc))
                        transport = "in-process-fallback"
                        result = spec.handler(self.session, validated, principal)
                else:
                    if transport == "in-process-fallback":
                        log.warning("mcp_unreachable_using_in_process_fallback", tool=tool_name)
                    # savepoint ⇒ a handler that crashes leaves no partial writes
                    with self.session.begin_nested():
                        result = spec.handler(self.session, validated, principal)
            except AppError as exc:
                record(self.session, principal=principal, action="tool.error", tool=tool_name, arguments=args,
                       result_summary=exc.message, severity="warning", analysis_id=run_id)
                return self._finish(
                    ToolResult(ok=False, tool=tool_name, status="error", mutating=mutating, transport=transport,
                               latency_ms=t.ms, error=exc.message, error_code=exc.code),
                    principal, args, run_id, chat_session_id,
                )
            except Exception as exc:  # noqa: BLE001
                log.exception("tool_execution_failed", tool=tool_name)
                return self._finish(
                    ToolResult(ok=False, tool=tool_name, status="error", mutating=mutating, transport=transport,
                               latency_ms=t.ms, error=f"Tool '{tool_name}' failed internally.",
                               error_code="tool_internal_error"),
                    principal, args, run_id, chat_session_id,
                )

        if transport_label:
            transport = transport_label
        if mutating:
            self._consume_confirmation(confirmation_id, result)
        res = self._finish(
            ToolResult(ok=True, tool=tool_name, result=result, transport=transport, latency_ms=t.ms,
                       mutating=mutating),
            principal, args, run_id, chat_session_id,
        )
        return res

    # -- confirmation helpers ------------------------------------------------ #
    def _check_confirmation(self, tool: str, args: dict, confirmation_id: str | None) -> ToolResult | None:
        if not confirmation_id:
            return ToolResult(
                ok=False, tool=tool, status="pending_confirmation", mutating=True,
                error=f"Tool '{tool}' mutates project state and requires an approved human confirmation.",
                error_code="confirmation_required",
            )
        conf = self.session.get(Confirmation, confirmation_id)
        if conf is None:
            return ToolResult(ok=False, tool=tool, status="pending_confirmation", mutating=True,
                              error=f"Confirmation '{confirmation_id}' not found.",
                              error_code="confirmation_required")
        if conf.status != "approved":
            return ToolResult(ok=False, tool=tool, status="pending_confirmation", mutating=True,
                              error=f"Confirmation '{confirmation_id}' is '{conf.status}', not approved.",
                              error_code="confirmation_required")
        if conf.result_json:
            return ToolResult(ok=False, tool=tool, status="error", mutating=True,
                              error="This confirmation was already consumed.", error_code="confirmation_consumed")
        if conf.tool_name != tool:
            return ToolResult(ok=False, tool=tool, status="error", mutating=True,
                              error="Confirmation does not match the requested tool.",
                              error_code="confirmation_mismatch")
        if (conf.payload_json or {}).get("digest") != payload_digest(tool, args):
            return ToolResult(ok=False, tool=tool, status="error", mutating=True,
                              error="Confirmation payload does not match the tool arguments (tampering guard).",
                              error_code="confirmation_mismatch")
        return None

    def _consume_confirmation(self, confirmation_id: str | None, result: dict) -> None:
        if not confirmation_id:
            return
        conf = self.session.get(Confirmation, confirmation_id)
        if conf is not None and not conf.result_json:
            conf.result_json = {"executed": True, "result": result}
            self.session.flush()

    @staticmethod
    def _jsonable(obj: Any) -> Any:
        """Columns are JSON: coerce datetimes/enum/path objects deterministically."""
        return json.loads(json.dumps(obj, default=str))

    def _finish(self, res: ToolResult, principal: Principal, args: dict, run_id: str | None,
                chat_session_id: str | None) -> ToolResult:
        res.execution_id = new_id("tex")
        res.result = self._jsonable(res.result) if res.result else res.result
        args = self._jsonable(args) or {}
        self.session.add(
            ToolExecution(
                id=res.execution_id, analysis_run_id=run_id, chat_session_id=chat_session_id,
                tool_name=res.tool, arguments_json=args, result_json=res.result if res.ok else {},
                status=res.status, error=res.error, transport=res.transport, mutating=res.mutating,
                requested_by=principal.user_id, latency_ms=res.latency_ms,
            )
        )
        if res.ok or res.status == "denied":
            record(
                self.session, principal=principal,
                action="tool.execute" if res.ok else "tool.denied",
                entity_type="tool", entity_id=res.tool, tool=res.tool, arguments=args,
                result_summary=(f"ok via {res.transport}" if res.ok else (res.error or "")),
                analysis_id=run_id, severity="info" if res.ok else "warning",
            )
        self.session.flush()
        return res


def create_confirmation(
    session: Session,
    *,
    principal: Principal,
    tool: str,
    args: dict[str, Any],
    action_label: str,
    summary: str,
    evidence: list[dict],
    project_id: str | None = None,
) -> Confirmation:
    conf = Confirmation(
        id=new_id("cfm"), project_id=project_id, tool_name=tool, action_label=action_label, summary=summary,
        payload_json={"args": args, "digest": payload_digest(tool, args)},
        evidence_json=evidence, status="pending", requested_by=principal.user_id,
    )
    session.add(conf)
    session.flush()
    record(session, principal=principal, action="confirmation.requested", entity_type="confirmation",
           entity_id=conf.id, tool=tool, arguments=args, result_summary=action_label)
    return conf
