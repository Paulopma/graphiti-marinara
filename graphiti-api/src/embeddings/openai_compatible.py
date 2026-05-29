from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

import httpx
from graphiti_core.embedder.client import EmbedderClient

from ..config import Settings

logger = logging.getLogger(__name__)


class OpenAICompatibleEmbedder(EmbedderClient):
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = httpx.AsyncClient(timeout=settings.embedding_timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    async def ping(self) -> bool:
        try:
            embeddings = await self._request_embeddings(["healthcheck"])
            return bool(embeddings and len(embeddings[0]) > 0)
        except Exception:
            logger.warning("OpenAI-compatible embedding endpoint is unreachable", exc_info=True)
            return False

    async def create(
        self, input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]]
    ) -> list[float]:
        inputs = self._normalize_create_input(input_data)
        embeddings = await self._request_embeddings(inputs)
        return embeddings[0]

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        return await self._request_embeddings(input_data_list)

    async def _request_embeddings(self, inputs: list[str]) -> list[list[float]]:
        response = await self._client.post(
            f"{str(self._settings.embedding_base_url).rstrip('/')}/embeddings",
            headers=self._headers(),
            json={"input": inputs, "model": self._settings.embedding_model},
        )
        response.raise_for_status()
        payload = response.json()
        embeddings = self._extract_embeddings(payload)
        if len(embeddings) != len(inputs):
            raise ValueError(
                f"Expected {len(inputs)} embeddings, received {len(embeddings)} instead."
            )
        return embeddings

    def _headers(self) -> dict[str, str]:
        api_key = self._settings.embedding_api_key or self._settings.deepseek_api_key
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def _normalize_create_input(
        self, input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]]
    ) -> list[str]:
        if isinstance(input_data, str):
            return [input_data]
        if isinstance(input_data, list) and all(isinstance(item, str) for item in input_data):
            return input_data
        raise TypeError("OpenAICompatibleEmbedder only supports text inputs.")

    def _extract_embeddings(self, payload: dict[str, Any]) -> list[list[float]]:
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError("Embedding response did not contain a data list.")

        embeddings: list[list[float]] = []
        for item in data:
            embedding = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(embedding, list):
                raise ValueError("Embedding response item is missing an embedding list.")
            embeddings.append([float(value) for value in embedding])
        return embeddings
