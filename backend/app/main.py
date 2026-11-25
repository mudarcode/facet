import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.analytics.sandbox import SandboxPool
from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.errors import install_error_handlers
from app.services.bootstrap import ensure_user

log = logging.getLogger("facet.api")
logging.getLogger("sqlglot").setLevel(logging.ERROR)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.objects_dir.mkdir(parents=True, exist_ok=True)
    if settings.seed_dev_user:
        with get_sessionmaker()() as db:
            ensure_user(db, email="dev@facet.local", name="Developer", token=settings.dev_token)
    pool = SandboxPool(settings.query_workers)
    await pool.start()
    app.state.sandbox = pool
    try:
        yield
    finally:
        await pool.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Facet API",
        version="0.1.0",
        description="SQL-powered analytics platform: datasets, sandboxed DuckDB queries, "
        "charts and dashboards.",
        openapi_url="/api/v1/openapi.json",
        docs_url="/docs",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Server-Timing", "Content-Disposition"],
    )

    @app.middleware("http")
    async def timing(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        t0 = time.perf_counter()
        response = await call_next(request)
        ms = (time.perf_counter() - t0) * 1000
        response.headers["Server-Timing"] = f"app;dur={ms:.1f}"
        log.info("%s %s %s %.1fms", request.method, request.url.path, response.status_code, ms)
        return response

    install_error_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
