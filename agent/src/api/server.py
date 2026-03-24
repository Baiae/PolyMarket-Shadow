from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import build_router

log = logging.getLogger(__name__)


def create_app(orchestrator) -> FastAPI:

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log.info("FastAPI ready — Flutter dashboard can connect")
        yield
        log.info("FastAPI shutting down")

    app = FastAPI(
        title="Poly-Shadow Agent API",
        description="REST bridge for the Flutter monitoring dashboard",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.include_router(build_router(orchestrator), prefix="/api")
    return app
