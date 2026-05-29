from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from graphiti_core import Graphiti
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from graphiti_core.edges import EntityEdge
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_client import OpenAIClient
from graphiti_core.nodes import EntityNode, EpisodeType
from graphiti_core.search.search_filters import ComparisonOperator, DateFilter, SearchFilters

from .config import Settings
from .embeddings.marinara_sidecar import MarinaraSidecarEmbedder
from .embeddings.openai_compatible import OpenAICompatibleEmbedder
from .schema.edges import EDGE_TYPE_MAP, EDGE_TYPES
from .schema.entities import ENTITY_TYPES

logger = logging.getLogger(__name__)


@dataclass
class DependencyStatus:
    name: str
    ok: bool
    detail: str


@dataclass
class HealthReport:
    ok: bool
    services: dict[str, DependencyStatus]


@dataclass
class CharacterAnchorResult:
    uuid: str
    name: str
    labels: list[str]
    role_class: str
    aliases: list[str]
    created: bool


class GraphitiService:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._ingest_lock = asyncio.Lock()
        self._startup_error: str | None = None
        self._embedder = self._build_embedder(settings)
        self._llm_config = LLMConfig(
            api_key=settings.deepseek_api_key,
            base_url=str(settings.deepseek_base_url),
            model=settings.deepseek_model,
            small_model=settings.deepseek_small_model,
        )
        self._llm_client = OpenAIClient(config=self._llm_config)
        self._reranker = OpenAIRerankerClient(config=self._llm_config)
        self._graphiti = Graphiti(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            llm_client=self._llm_client,
            embedder=self._embedder,
            cross_encoder=self._reranker,
            store_raw_episode_content=settings.graphiti_store_raw_episode_content,
        )

    @property
    def graphiti(self) -> Graphiti:
        return self._graphiti

    def _build_embedder(self, settings: Settings):
        if settings.embedding_provider == "marinara_sidecar":
            return MarinaraSidecarEmbedder(settings)
        if settings.embedding_provider == "openai_compatible":
            return OpenAICompatibleEmbedder(settings)
        raise ValueError(f"Unsupported embedding provider: {settings.embedding_provider}")

    async def initialize(self) -> None:
        try:
            await asyncio.wait_for(
                self._graphiti.build_indices_and_constraints(),
                timeout=self._settings.graphiti_startup_timeout_seconds,
            )
            self._startup_error = None
        except TimeoutError:
            self._startup_error = (
                "timed out while building Graphiti indices and constraints"
            )
            logger.exception("Graphiti startup initialization timed out")
        except Exception as exc:
            self._startup_error = str(exc)
            logger.exception("Graphiti startup initialization failed")

    async def close(self) -> None:
        try:
            await self._graphiti.close()
        finally:
            await self._embedder.close()

    async def check_health(self) -> HealthReport:
        services = {
            "neo4j": await self._check_neo4j(),
            "deepseek": await self._check_deepseek(),
            "embeddings": await self._check_embeddings(),
        }
        if self._startup_error and services["neo4j"].ok:
            services["neo4j"] = DependencyStatus(
                name="neo4j",
                ok=False,
                detail=f"startup initialization failed: {self._startup_error}",
            )
        return HealthReport(ok=all(status.ok for status in services.values()), services=services)

    async def add_episode(
        self,
        *,
        campaign_id: str,
        episode_uuid: str,
        name: str,
        episode_body: str,
        source_description: str,
        reference_time: datetime,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        async with self._ingest_lock:
            return await self._graphiti.add_episode(
                name=name,
                episode_body=episode_body,
                source_description=source_description,
                reference_time=reference_time,
                source=EpisodeType.message,
                group_id=campaign_id,
                update_communities=self._settings.graphiti_update_communities,
                entity_types=ENTITY_TYPES,
                edge_types=EDGE_TYPES,
                edge_type_map=EDGE_TYPE_MAP,
            )

    async def upsert_character_anchor(
        self,
        *,
        campaign_id: str,
        name: str,
        role_class: str,
        aliases: list[str] | None = None,
    ) -> CharacterAnchorResult:
        aliases = _normalize_aliases(aliases or [], name)
        existing_uuid = await self._find_character_anchor_uuid(campaign_id, name, aliases)
        created = existing_uuid is None
        labels = ["Character", _role_class_label(role_class)]
        summary = _anchor_summary(name, role_class)

        if existing_uuid:
            node = await EntityNode.get_by_uuid(self._graphiti.driver, existing_uuid)
            node.labels = _merge_node_labels(node.labels, labels)
            node.attributes = dict(node.attributes or {})
            node.attributes["role_class"] = role_class
            node.attributes["aliases"] = aliases
            if not node.summary:
                node.summary = summary
        else:
            node = EntityNode(
                name=name,
                group_id=campaign_id,
                labels=labels,
                summary=summary,
                attributes={"role_class": role_class, "aliases": aliases},
            )

        if node.name_embedding is None:
            await node.generate_name_embedding(self._embedder)

        await node.save(self._graphiti.driver)
        await self._apply_character_anchor_labels(node.uuid, role_class, aliases)

        return CharacterAnchorResult(
            uuid=node.uuid,
            name=node.name,
            labels=["Entity", *_merge_node_labels(node.labels, labels)],
            role_class=role_class,
            aliases=aliases,
            created=created,
        )

    async def search(
        self,
        *,
        campaign_id: str,
        query: str,
        limit: int,
        center_node_uuid: str | None = None,
        entity_type_filter: list[str] | None = None,
        as_of_in_game_time: datetime | None = None,
    ) -> tuple[list[EntityEdge], list[EntityNode]]:
        filters = self._build_search_filters(entity_type_filter, as_of_in_game_time)
        edges = await self._graphiti.search(
            query=query,
            center_node_uuid=center_node_uuid,
            group_ids=[campaign_id],
            num_results=limit,
            search_filter=filters,
        )

        node_uuids = {
            edge.source_node_uuid
            for edge in edges
            if getattr(edge, "source_node_uuid", None) is not None
        }
        node_uuids.update(
            edge.target_node_uuid
            for edge in edges
            if getattr(edge, "target_node_uuid", None) is not None
        )

        nodes: list[EntityNode] = []
        if node_uuids:
            nodes = await EntityNode.get_by_uuids(
                self._graphiti.driver,
                sorted(node_uuids),
                group_id=campaign_id,
            )

        return edges, nodes

    async def _find_character_anchor_uuid(
        self,
        campaign_id: str,
        name: str,
        aliases: list[str],
    ) -> str | None:
        records, _, _ = await self._graphiti.driver.execute_query(
            """
            MATCH (n:Entity {group_id: $group_id})
            WHERE toLower(n.name) = toLower($name)
               OR any(existing_alias IN coalesce(n.aliases, [])
                      WHERE toLower(existing_alias) = toLower($name))
               OR any(input_alias IN $aliases
                      WHERE toLower(n.name) = toLower(input_alias))
               OR any(existing_alias IN coalesce(n.aliases, [])
                      WHERE any(input_alias IN $aliases
                                WHERE toLower(existing_alias) = toLower(input_alias)))
            RETURN n.uuid AS uuid
            LIMIT 1
            """,
            group_id=campaign_id,
            name=name,
            aliases=aliases,
            routing_="r",
        )
        if not records:
            return None
        return records[0].get("uuid")

    async def _apply_character_anchor_labels(
        self,
        uuid: str,
        role_class: str,
        aliases: list[str],
    ) -> None:
        if role_class == "persona":
            label_query = "REMOVE n:PrimaryCharacter SET n:Character:Persona"
        elif role_class == "primary_character":
            label_query = "REMOVE n:Persona SET n:Character:PrimaryCharacter"
        else:
            raise ValueError(f"Unsupported character anchor role class: {role_class}")

        await self._graphiti.driver.execute_query(
            f"""
            MATCH (n:Entity {{uuid: $uuid}})
            {label_query}
            SET n.role_class = $role_class,
                n.aliases = $aliases
            RETURN n.uuid AS uuid
            """,
            uuid=uuid,
            role_class=role_class,
            aliases=aliases,
        )

    def _build_search_filters(
        self,
        entity_type_filter: list[str] | None,
        as_of_in_game_time: datetime | None,
    ) -> SearchFilters:
        filters = SearchFilters()

        if entity_type_filter:
            filters.node_labels = entity_type_filter

        if as_of_in_game_time is not None:
            valid_group = [
                DateFilter(
                    date=as_of_in_game_time,
                    comparison_operator=ComparisonOperator.less_than_equal,
                )
            ]
            invalid_group = [
                DateFilter(
                    date=as_of_in_game_time,
                    comparison_operator=ComparisonOperator.greater_than,
                )
            ]
            invalid_null_group = [
                DateFilter(date=None, comparison_operator=ComparisonOperator.is_null)
            ]
            filters.valid_at = [valid_group, invalid_null_group]
            filters.invalid_at = [invalid_group, invalid_null_group]

        return filters

    async def _check_neo4j(self) -> DependencyStatus:
        try:
            records, _, _ = await asyncio.wait_for(
                self._graphiti.driver.execute_query("RETURN 1 AS ok"),
                timeout=self._settings.neo4j_health_timeout_seconds,
            )
            ok = bool(records and records[0].get("ok") == 1)
            detail = "connected" if ok else "unexpected response"
            return DependencyStatus(name="neo4j", ok=ok, detail=detail)
        except TimeoutError:
            return DependencyStatus(name="neo4j", ok=False, detail="health check timed out")
        except Exception as exc:
            return DependencyStatus(name="neo4j", ok=False, detail=str(exc))

    async def _check_deepseek(self) -> DependencyStatus:
        try:
            response = await self._llm_client.client.chat.completions.create(
                model=self._settings.deepseek_model,
                messages=[{"role": "user", "content": "Reply with OK."}],
                max_tokens=1,
                timeout=self._settings.health_llm_timeout_seconds,
            )
            content = response.choices[0].message.content if response.choices else None
            ok = bool(content)
            detail = "reachable" if ok else "empty completion"
            return DependencyStatus(name="deepseek", ok=ok, detail=detail)
        except Exception as exc:
            return DependencyStatus(name="deepseek", ok=False, detail=str(exc))

    async def _check_embeddings(self) -> DependencyStatus:
        ok = await self._embedder.ping()
        detail = "reachable" if ok else "sidecar unavailable; zero-vector fallback active"
        return DependencyStatus(name="embeddings", ok=ok, detail=detail)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_aliases(aliases: list[str], name: str) -> list[str]:
    normalized: list[str] = []
    seen = {name.casefold()}
    for alias in aliases:
        clean_alias = alias.strip()
        folded = clean_alias.casefold()
        if clean_alias and folded not in seen:
            normalized.append(clean_alias)
            seen.add(folded)
    return normalized


def _role_class_label(role_class: str) -> str:
    if role_class == "persona":
        return "Persona"
    if role_class == "primary_character":
        return "PrimaryCharacter"
    raise ValueError(f"Unsupported character anchor role class: {role_class}")


def _anchor_summary(name: str, role_class: str) -> str:
    if role_class == "persona":
        return f"{name} is the campaign persona and central viewpoint character."
    return f"{name} is a primary campaign character with persistent narrative agency."


def _merge_node_labels(existing: list[str], required: list[str]) -> list[str]:
    labels: list[str] = []
    for label in [*existing, *required]:
        if label != "Entity" and label not in labels:
            labels.append(label)
    return labels
