import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import build_router
from config import settings

log = logging.getLogger(__name__)


def create_app(orchestrator) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(orchestrator.run(), name="poly-shadow-agent")
        log.info("FastAPI ready; v0.2 paper core starting")
        try:
            yield
        finally:
            orchestrator.stop()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            log.info("FastAPI and paper core stopped")

    app = FastAPI(
        title="Poly-Shadow Agent API",
        description="Local control and observation API for the truthful v0.2 paper core",
        version="0.2.0",
        lifespan=lifespan,
    )
    if settings.api_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.api_allowed_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "X-Poly-Shadow-Control-Token"],
        )
    app.include_router(build_router(orchestrator), prefix="/api")
    return app
