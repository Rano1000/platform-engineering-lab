"""FastAPI application and lifecycle."""

from contextlib import asynccontextmanager
import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from golden_path_api.config import Settings, load_settings
from golden_path_api.logging_config import configure_logging
from golden_path_api.metrics import REQUEST_DURATION, REQUESTS


def create_app(settings: Settings | None = None) -> FastAPI:
    configured = settings or load_settings()
    configure_logging(configured.log_level)
    logger = logging.getLogger("golden_path_api")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.ready = True
        logger.info("application started")
        try:
            yield
        finally:
            app.state.ready = False
            logger.info("application stopped")

    app = FastAPI(
        title=configured.name,
        version=configured.version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.ready = False

    @app.middleware("http")
    async def observe_request(request: Request, call_next):
        request_id = request.headers.get("x-request-id", str(uuid4()))
        started = perf_counter()
        response = await call_next(request)
        duration = perf_counter() - started
        path = request.url.path
        REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        REQUEST_DURATION.labels(request.method, path).observe(duration)
        response.headers["x-request-id"] = request_id
        logger.info(
            "request completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": path,
                "status": response.status_code,
                "duration_ms": round(duration * 1000, 3),
            },
        )
        return response

    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "name": configured.name,
            "environment": configured.environment,
            "version": configured.version,
            "revision": configured.revision,
        }

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready")
    async def ready(request: Request, response: Response) -> dict[str, str]:
        if not request.app.state.ready:
            response.status_code = 503
            return {"status": "not-ready"}
        return {"status": "ready"}

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
