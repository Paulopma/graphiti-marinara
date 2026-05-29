from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from pydantic import BaseModel, Field, ValidationError

from ..config import get_settings
from ..graphiti_client import GraphitiService, ensure_utc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tools", tags=["tools"])

SEARCH_TOOL_NAME = "graph_memory_search"
INGEST_TOOL_NAME = "graph_memory_ingest"
SEARCH_TOOL_ALIASES = {SEARCH_TOOL_NAME, "search"}
INGEST_TOOL_ALIASES = {INGEST_TOOL_NAME, "ingest"}


class MarinaraToolContext(BaseModel):
    chat_id: str | None = Field(default=None, alias="chatId")
    agent_type: str | None = Field(default=None, alias="agentType")
    phase: str | None = None


class MarinaraToolEnvelope(BaseModel):
    tool: str = Field(min_length=1)
    arguments: dict[str, Any]
    context: MarinaraToolContext | None = None


class SearchToolArguments(BaseModel):
    user_message: str | None = Field(default=None, min_length=1)
    query: str | None = Field(default=None, min_length=1)
    chat_id: str | None = None
    group_id: str | None = None
    limit: int | None = Field(default=None, ge=1)
    center_node_uuid: str | None = None
    entity_type_filter: list[str] | None = None
    as_of_in_game_time: datetime | None = None


class IngestToolArguments(BaseModel):
    chat_id: str | None = None
    group_id: str | None = None
    user_message: str = Field(min_length=1)
    assistant_message: str = Field(min_length=1)
    message_index: int | None = Field(default=None, ge=0)
    reference_time: datetime | None = None


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


class SearchToolResponse(BaseModel):
    status: str
    tool: str
    group_id: str
    query: str
    facts: list[SearchFact]
    entities: list[SearchEntity]
    fallback_text: str


class IngestToolResponse(BaseModel):
    status: str
    tool: str
    episode_uuid: str
    group_id: str


@router.post("/search", response_model=SearchToolResponse)
async def search_tool(request: Request) -> SearchToolResponse:
    envelope = _parse_envelope(await _read_json_body(request), SEARCH_TOOL_ALIASES)
    payload = _validate_arguments(SearchToolArguments, envelope.arguments, SEARCH_TOOL_NAME)
    group_id = _resolve_group_id(request, payload.chat_id, payload.group_id, envelope.context)
    settings = get_settings()
    service = _get_graphiti_service(request)
    limit = min(payload.limit or settings.search_default_limit, settings.search_max_limit)
    search_query = _build_search_query(payload)

    edges, nodes = await service.search(
        campaign_id=group_id,
        query=search_query,
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
    durable_edges = [
        edge
        for edge in edges
        if _is_durable_memory_edge(edge.name, node_lookup.get(edge.source_node_uuid))
    ]
    durable_node_uuids = {
        node_uuid
        for edge in durable_edges
        for node_uuid in (edge.source_node_uuid, edge.target_node_uuid)
        if node_uuid
    }
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
        for edge in durable_edges
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
        if node.uuid in durable_node_uuids
    ]
    logger.info(
        "Marinara Graphiti search completed tool=%s group_id=%s query=%r facts=%d entities=%d",
        envelope.tool,
        group_id,
        search_query,
        len(facts),
        len(entities),
    )

    return SearchToolResponse(
        status="ok",
        tool=envelope.tool,
        group_id=group_id,
        query=search_query,
        facts=facts,
        entities=entities,
        fallback_text=_build_fallback_text(facts, entities),
    )


@router.post("/ingest", response_model=IngestToolResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_tool(
    request: Request,
    background_tasks: BackgroundTasks,
) -> IngestToolResponse:
    envelope = _parse_envelope(await _read_json_body(request), INGEST_TOOL_ALIASES)
    payload = _validate_arguments(IngestToolArguments, envelope.arguments, INGEST_TOOL_NAME)
    group_id = _resolve_group_id(request, payload.chat_id, payload.group_id, envelope.context)
    service = _get_graphiti_service(request)
    episode_uuid = str(uuid4())
    name = (
        f"campaign:{group_id}:turn:{payload.message_index}"
        if payload.message_index is not None
        else f"campaign:{group_id}:episode:{episode_uuid}"
    )

    metadata = _build_ingest_metadata(payload)

    episode_body = f"User: {payload.user_message}\n\nAssistant: {payload.assistant_message}"
    source_description = (
        "Marinara durable memory webhook. Extract only long-term roleplay memory; "
        "ignore transient tracker state such as current location, weather, background, "
        "expression, outfit, active quest progress, and numeric persona stats."
    )
    if payload.message_index is not None:
        source_description = f"Marinara turn {payload.message_index}. {source_description}"

    reference_time = (
        ensure_utc(payload.reference_time)
        if payload.reference_time is not None
        else datetime.now(timezone.utc)
    )
    background_tasks.add_task(
        _ingest_episode,
        service,
        group_id,
        episode_uuid,
        name,
        episode_body,
        source_description,
        reference_time,
        metadata or None,
    )
    logger.info(
        "Marinara Graphiti ingest queued",
        extra={
            "tool": envelope.tool,
            "group_id": group_id,
            "episode_uuid": episode_uuid,
            "message_index": payload.message_index,
        },
    )

    return IngestToolResponse(
        status="queued",
        tool=envelope.tool,
        episode_uuid=episode_uuid,
        group_id=group_id,
    )


async def _read_json_body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body must be valid JSON.",
        ) from exc

    if not isinstance(body, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Marinara tool payload must be a JSON object with 'tool' and 'arguments'.",
        )

    return body


def _parse_envelope(body: dict[str, Any], expected_tools: set[str]) -> MarinaraToolEnvelope:
    missing_fields = [field for field in ("tool", "arguments") if field not in body]
    if missing_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Marinara tool payload is missing required field(s): "
                + ", ".join(missing_fields)
            ),
        )

    if body["tool"] not in expected_tools:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Expected tool {sorted(expected_tools)} but received "
                f"'{body['tool']}'."
            ),
        )

    if not isinstance(body["arguments"], dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'arguments' must be a JSON object.",
        )

    return MarinaraToolEnvelope.model_validate(body)


def _validate_arguments(model: type[BaseModel], arguments: dict[str, Any], tool_name: str) -> BaseModel:
    try:
        return model.model_validate(arguments)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {tool_name} arguments: {_format_validation_error(exc)}",
        ) from exc


def _format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error.get("loc", ())) or "body"
        message = error.get("msg", "invalid value")
        parts.append(f"{location}: {message}")
    return "; ".join(parts)


def _ensure_group_id(chat_id: str | None, group_id: str | None) -> str:
    if chat_id and group_id and chat_id != group_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either chat_id or group_id, or use matching values for both.",
        )

    resolved = chat_id or group_id
    if not resolved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either chat_id or group_id is required.",
        )

    return resolved


def _resolve_group_id(
    request: Request,
    chat_id: str | None,
    group_id: str | None,
    context: MarinaraToolContext | None,
) -> str:
    pinned_group_id = request.query_params.get("chat_id") or request.query_params.get("group_id")
    if pinned_group_id:
        body_group_id = chat_id or group_id
        if body_group_id and body_group_id != pinned_group_id:
            logger.warning(
                "Ignoring Marinara tool body group id because webhook URL pins the chat id pinned_group_id=%s body_group_id=%s",
                pinned_group_id,
                body_group_id,
            )
        return pinned_group_id

    context_chat_id = context.chat_id if context else None
    if context_chat_id:
        body_group_id = chat_id or group_id
        if body_group_id and body_group_id != context_chat_id:
            logger.warning(
                "Ignoring Marinara tool body group id because webhook context supplies the chat id context_chat_id=%s body_group_id=%s",
                context_chat_id,
                body_group_id,
            )
        return context_chat_id

    return _ensure_group_id(chat_id, group_id)


def _build_search_query(payload: SearchToolArguments) -> str:
    search_query = payload.query or payload.user_message
    if not search_query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either user_message or query is required.",
        )
    return search_query.strip()


def _get_graphiti_service(request: Request) -> GraphitiService:
    service = getattr(request.app.state, "graphiti", None) or getattr(
        request.app.state, "graphiti_service", None
    )
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Graphiti service is not available on application state.",
        )
    return service


def _normalize_attributes(attributes: dict[str, object] | None) -> dict[str, object]:
    return dict(attributes or {})


def _is_durable_memory_edge(edge_name: str, source_node: Any) -> bool:
    if edge_name != "LOCATED_AT":
        return True

    labels = set(getattr(source_node, "labels", []) or [])
    return "Item" in labels


def _build_ingest_metadata(payload: IngestToolArguments) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if payload.message_index is not None:
        metadata["message_index"] = payload.message_index
    return metadata


def _build_fallback_text(facts: list[SearchFact], entities: list[SearchEntity]) -> str:
    lines: list[str] = []
    if facts:
        lines.append("Graphiti long-term memory:")
        lines.extend(f"- {fact.fact}" for fact in facts)
    if not lines:
        return "No relevant facts or entities found."
    return "\n".join(lines)


async def _ingest_episode(
    service: GraphitiService,
    group_id: str,
    episode_uuid: str,
    name: str,
    episode_body: str,
    source_description: str,
    reference_time: datetime,
    metadata: dict[str, Any] | None,
) -> None:
    try:
        await service.add_episode(
            campaign_id=group_id,
            episode_uuid=episode_uuid,
            name=name,
            episode_body=episode_body,
            source_description=source_description,
            reference_time=reference_time,
            metadata=metadata,
        )
        logger.info(
            "Marinara Graphiti ingest completed",
            extra={"group_id": group_id, "episode_uuid": episode_uuid},
        )
    except Exception:
        logger.exception(
            "Marinara Graphiti ingest failed",
            extra={"group_id": group_id, "episode_uuid": episode_uuid},
        )
