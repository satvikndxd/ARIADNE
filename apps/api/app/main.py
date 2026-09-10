"""FastAPI application factory."""
from __future__ import annotations

import sys
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import REPO_ROOT, settings
from app.core.errors import AppError, app_error_handler, unhandled_error_handler
from app.core.ids import new_id
from app.core.logging import configure_logging, get_logger, request_id_var
from app.db.base import init_db

sys.path.insert(0, str(REPO_ROOT / "packages" / "evaluation"))

from app.routes import (  # noqa: E402
    analysis,
    audit,
    chat,
    components,
    documents,
    evaluation,
    findings,
    mcp_bridge,
    projects,
    rag,
    revisions,
    system,
)

log = get_logger("ariadne.api")


def create_app() -> FastAPI:
    configure_logging(json_output=settings.ariadne_env != "development")
    app = FastAPI(
        title="ARIADNE API",
        version="0.1.0",
        description="Revision-aware multimodal engineering impact analysis (decision support, not autonomy).",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-request-id", "x-process-ms"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or new_id("req")
        request_id_var.set(rid)
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:  # pragma: no cover - safety net
            log.exception("unhandled_middleware_error", path=request.url.path)
            return JSONResponse(status_code=500,
                                content={"error": {"code": "internal_error", "message": "Unexpected error."}})
        ms = round((time.perf_counter() - t0) * 1000, 2)
        response.headers["x-request-id"] = rid
        response.headers["x-process-ms"] = str(ms)
        if request.url.path not in ("/health", "/docs", "/openapi.json"):
            log.info("http_request", method=request.method, path=request.url.path,
                     status=response.status_code, latency_ms=ms)
        return response

    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    for router in (system.router, projects.router, revisions.router, components.router, analysis.router,
                   findings.router, documents.router, rag.router, chat.router, audit.router,
                   evaluation.router, mcp_bridge.router):
        app.include_router(router)

    drawings_dir = settings.drawings_dir
    drawings_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/drawings", StaticFiles(directory=str(drawings_dir)), name="drawings")

    @app.on_event("startup")
    def _startup() -> None:
        init_db()
        log.info("api_started", demo_mode=settings.demo_mode, db="sqlite" if settings.is_sqlite else "postgres",
                 vector_store=settings.effective_vector_store, graph_store=settings.effective_graph_store)

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("app.main:app", host=settings.api_host, port=settings.api_port, reload=False)
