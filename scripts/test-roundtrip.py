#!/usr/bin/env python3
"""Smoke test for the Graphiti API round trip."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any


EPISODES = [
    "Lona conheceu Marcus na taverna em Noer. Ele ofereceu 20 moedas para entregar um pacote.",
    "Lona aceitou o trabalho e prometeu entregar.",
    "No caminho, Lona descobriu que o pacote continha um item roubado.",
    "Lona decidiu nao entregar o pacote, traindo o acordo com Marcus.",
    "Marcus descobriu a traicao e jurou vinganca.",
]


def request_json(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{url} returned HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to reach {url}: {exc}") from exc


def get_json(url: str, timeout: int) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{url} returned HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to reach {url}: {exc}") from exc


def wait_for_search(base_url: str, payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            result = request_json(f"{base_url}/search", payload, timeout=15)
            facts = result.get("facts")
            entities = result.get("entities")
            if (isinstance(facts, list) and facts) or (isinstance(entities, list) and entities):
                return result
        except Exception as exc:  # noqa: BLE001 - surface the last meaningful failure
            last_error = exc
        time.sleep(2)
    if last_error is not None:
        raise RuntimeError(f"Search did not stabilize before timeout: {last_error}") from last_error
    raise RuntimeError("Search did not stabilize before timeout")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("GRAPHITI_API_URL", "http://localhost:8765"),
        help="Graphiti API base URL",
    )
    parser.add_argument(
        "--campaign-id",
        default=os.getenv("GRAPHITI_DEFAULT_CAMPAIGN_ID", "marinara-smoke-test"),
    )
    parser.add_argument("--timeout-seconds", type=int, default=90)
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()

    health = get_json(f"{args.base_url}/health", timeout=15)
    print("health:", json.dumps(health, ensure_ascii=True))

    reference_time = "2026-05-28T20:00:00-03:00"
    for index, episode in enumerate(EPISODES, start=1):
        payload = {
            "campaign_id": args.campaign_id,
            "episode_body": episode,
            "source_description": f"Smoke test episode {index}",
            "reference_time": reference_time,
            "metadata": {
                "location": "Noer",
                "present_characters": ["Lona", "Marcus"],
                "turn_number": index,
            },
        }
        result = request_json(f"{args.base_url}/episodes/add", payload, timeout=30)
        print(f"episode {index}:", json.dumps(result, ensure_ascii=True))
        time.sleep(0.5)

    queries = [
        "Marcus",
        "Lona promises",
    ]
    for query in queries:
        payload = {
            "campaign_id": args.campaign_id,
            "query": query,
            "limit": args.limit,
            "as_of_in_game_time": reference_time,
        }
        result = wait_for_search(args.base_url, payload, args.timeout_seconds)
        print(f"search {query!r}:", json.dumps(result, ensure_ascii=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
