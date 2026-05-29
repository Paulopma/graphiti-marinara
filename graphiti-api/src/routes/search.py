from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..config import get_settings
from ..graphiti_client import GraphitiService, ensure_utc

router = APIRouter(tags=["search"])


class SearchRequest(BaseModel):
    campaign_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    limit: int | None = Field(default=None, ge=1)
    center_node_uuid: str | None = None
    entity_type_filter: list[str] | None = None
    as_of_in_game_time: datetime | None = None


class SearchFact(BaseModel):
    fact: str
    source_entity: str | None = None
    target_entity: str | None = None
    edge_type: str
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    episode_uuid: str | None = None
    edge_uuid: str
    attributes: dict[str, object] = Field(default_factory=dict)


class SearchEntity(BaseModel):
    uuid: str
    name: str
    labels: list[str]
    summary: str
    attributes: dict[str, object] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    facts: list[SearchFact]
    entities: list[SearchEntity]


@router.post("/search", response_model=SearchResponse)
async def search(payload: SearchRequest, request: Request) -> SearchResponse:
    settings = get_settings()
    service: GraphitiService = request.app.state.graphiti_service
    limit = min(payload.limit or settings.search_default_limit, settings.search_max_limit)

    edges, nodes = await service.search(
        campaign_id=payload.campaign_id,
        query=payload.query,
        limit=limit,
        center_node_uuid=payload.center_node_uuid,
        entity_type_filter=payload.entity_type_filter,
        as_of_in_game_time=(
            ensure_utc(payload.as_of_in_game_time)
            if payload.as_of_in_game_time is not None
            else None
        ),
    )

    node_lookup = {node.uuid: node for node in nodes}
    facts = [
        SearchFact(
            fact=edge.fact,
            source_entity=node_lookup.get(edge.source_node_uuid).name
            if node_lookup.get(edge.source_node_uuid)
            else None,
            target_entity=node_lookup.get(edge.target_node_uuid).name
            if node_lookup.get(edge.target_node_uuid)
            else None,
            edge_type=edge.name,
            valid_from=edge.valid_at,
            valid_until=edge.invalid_at,
            episode_uuid=edge.episodes[0] if edge.episodes else None,
            edge_uuid=edge.uuid,
            attributes=_normalize_attributes(edge.attributes),
        )
        for edge in edges
    ]
    entities = [
        SearchEntity(
            uuid=node.uuid,
            name=node.name,
            labels=node.labels,
            summary=node.summary,
            attributes=_normalize_attributes(node.attributes),
        )
        for node in nodes
    ]

    return SearchResponse(facts=facts, entities=entities)


def _normalize_attributes(attributes: dict[str, object] | None) -> dict[str, object]:
    return dict(attributes or {})
