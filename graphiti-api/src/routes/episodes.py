from __future__ import annotations

import logging
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..graphiti_client import GraphitiService, ensure_utc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/episodes", tags=["episodes"])


class AddEpisodeRequest(BaseModel):
    campaign_id: str = Field(min_length=1)
    episode_body: str = Field(min_length=1)
    source_description: str = Field(min_length=1)
    reference_time: datetime
    metadata: dict[str, object] | None = None


class AddEpisodeResponse(BaseModel):
    episode_uuid: str
    queued: bool


class DeleteEpisodeResponse(BaseModel):
    detail: str


@router.post("/add", response_model=AddEpisodeResponse, status_code=status.HTTP_202_ACCEPTED)
async def add_episode(
    payload: AddEpisodeRequest,
    background_tasks: BackgroundTasks,
    request: Request,
) -> AddEpisodeResponse:
    service: GraphitiService = request.app.state.graphiti_service
    episode_uuid = str(uuid4())
    episode_name = payload.metadata.get("turn_number") if payload.metadata else None
    name = (
        f"campaign:{payload.campaign_id}:turn:{episode_name}"
        if episode_name is not None
        else f"campaign:{payload.campaign_id}:episode:{episode_uuid}"
    )

    background_tasks.add_task(
        _ingest_episode,
        service,
        payload,
        episode_uuid,
        name,
    )
    return AddEpisodeResponse(episode_uuid=episode_uuid, queued=True)


@router.delete("/{episode_uuid}", response_model=DeleteEpisodeResponse, status_code=501)
async def delete_episode(episode_uuid: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content=DeleteEpisodeResponse(
            detail=(
                f"Episode deletion for {episode_uuid} is not implemented because "
                "Graphiti does not expose a stable rollback API for extracted graph state."
            )
        ).model_dump(),
    )


async def _ingest_episode(
    service: GraphitiService,
    payload: AddEpisodeRequest,
    episode_uuid: str,
    name: str,
) -> None:
    try:
        await service.add_episode(
            campaign_id=payload.campaign_id,
            episode_uuid=episode_uuid,
            name=name,
            episode_body=payload.episode_body,
            source_description=payload.source_description,
            reference_time=ensure_utc(payload.reference_time),
            metadata=payload.metadata,
        )
        logger.info(
            "Episode ingested",
            extra={"campaign_id": payload.campaign_id, "episode_uuid": episode_uuid},
        )
    except Exception:
        logger.exception(
            "Episode ingestion failed",
            extra={"campaign_id": payload.campaign_id, "episode_uuid": episode_uuid},
        )
