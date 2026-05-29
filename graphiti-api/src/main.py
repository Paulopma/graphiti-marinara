from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .graphiti_client import GraphitiService
from .routes.campaigns import router as campaigns_router
from .routes.episodes import router as episodes_router
from .routes.health import router as health_router
from .routes.search import router as search_router
from .routes.tools import router as tools_router


def configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    service = GraphitiService(settings)
    await service.initialize()
    app.state.settings = settings
    app.state.graphiti = service
    app.state.graphiti_service = service
    try:
        yield
    finally:
        await service.close()


app = FastAPI(title="Graphiti API", version="0.1.0", lifespan=lifespan)
app.include_router(health_router)
app.include_router(campaigns_router)
app.include_router(episodes_router)
app.include_router(search_router)
app.include_router(tools_router)
