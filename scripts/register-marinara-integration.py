#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any


DEFAULT_MARINARA_URL = "http://127.0.0.1:7860"
DEFAULT_GRAPHITI_URL = "http://localhost:8765"
DEFAULT_CONNECTION_ID = "tMvUOjeEj8Fv48OmWvo5n"


SEARCH_TOOL_NAME = "graph_memory_search"
INGEST_TOOL_NAME = "graph_memory_ingest"
RETRIEVE_AGENT_TYPE = "custom-graph-memory-retrieve"
INGEST_AGENT_TYPE = "custom-graph-memory-ingest"


SEARCH_PROMPT = """You retrieve long-term graph memory for the current Marinara chat.

Call graph_memory_search exactly once before generation. Marinara sends the current chat id in the tool webhook context automatically; do not invent or pass chat_id/group_id.
Pass the latest user message verbatim as user_message. Do not summarize it, rewrite it, extract entities, build a query, or add World State / Character Tracker / Quest Tracker data. The Graphiti backend builds the search query and filters transient tracker overlap.

After the tool returns, return only its fallback_text. Do not answer the user, roleplay, explain the tool, or invent tool failures. This agent is context injection for the main model.
"""


INGEST_PROMPT = """You persist durable events from the current Marinara turn into graph memory.

Call graph_memory_ingest exactly once after the assistant reply is available. Marinara sends the current chat id in the tool webhook context automatically; do not invent or pass chat_id/group_id.
Pass only the user's latest message as user_message, the assistant's latest reply as assistant_message, and message_index if it is already available. Do not pass World State, location, present characters, time, Character Tracker, Quest Tracker, Background, Expression Engine, Persona Stats, or editor notes. The Graphiti backend stores the raw turn and performs durable memory extraction itself.

After the tool returns, report the tool status and episode_uuid in one line. Do not invent success if the tool fails. Do not rewrite the assistant message.
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Register Graphiti custom tools and agents in Marinara."
    )
    parser.add_argument("--marinara-url", default=DEFAULT_MARINARA_URL)
    parser.add_argument("--graphiti-url", default=DEFAULT_GRAPHITI_URL)
    parser.add_argument("--connection-id", default=DEFAULT_CONNECTION_ID)
    parser.add_argument(
        "--chat-id",
        help=(
            "Optional Marinara chat id to enable Graphiti agents/tools on. "
            "Registration still runs first."
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    client = MarinaraClient(args.marinara_url)
    desired_tools = build_tools(args.graphiti_url)
    desired_agents = build_agents(args.connection_id)

    if args.dry_run:
        print(json.dumps({"tools": desired_tools, "agents": desired_agents}, indent=2))
        return 0

    existing_tools = client.get("/custom-tools")
    existing_agents = client.get("/agents")

    for tool in desired_tools:
        current = find_by(existing_tools, "name", tool["name"])
        if current:
            client.patch(f"/custom-tools/{current['id']}", tool)
            print(f"updated tool: {tool['name']}")
        else:
            created = client.post("/custom-tools", tool)
            print(f"created tool: {created.get('name', tool['name'])}")

    for agent in desired_agents:
        current = find_agent(existing_agents, agent["type"])
        if current:
            payload = dict(agent)
            payload.pop("type", None)
            client.patch(f"/agents/{current['id']}", payload)
            print(f"updated agent: {agent['name']}")
        else:
            created = client.post("/agents", agent)
            print(f"created agent: {created.get('name', agent['name'])}")

    if args.chat_id:
        client.patch(
            f"/chats/{args.chat_id}/metadata",
            {
                "enableAgents": True,
                "enableTools": False,
                "activeAgentIds": [INGEST_AGENT_TYPE, RETRIEVE_AGENT_TYPE],
                "activeToolIds": [],
            },
        )
        print(f"enabled Graphiti agents/tools on chat: {args.chat_id}")

    return 0


class MarinaraClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        return self._request("POST", path, payload)

    def patch(self, path: str, payload: dict[str, Any]) -> Any:
        return self._request("PATCH", path, payload)

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.base_url}/api{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "x-marinara-csrf": "1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} failed: {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"{method} {path} failed: {exc.reason}") from exc
        return json.loads(raw) if raw else None


def build_tools(graphiti_url: str) -> list[dict[str, Any]]:
    graphiti_url = graphiti_url.rstrip("/")
    search_url = f"{graphiti_url}/tools/search"
    ingest_url = f"{graphiti_url}/tools/ingest"
    search_properties: dict[str, Any] = {
        "user_message": {
            "type": "string",
            "description": "Latest user message, copied verbatim. The backend builds the Graphiti query.",
        },
        "limit": {
            "type": "number",
            "description": "Maximum facts to return. Default 8.",
        },
        "center_node_uuid": {
            "type": "string",
            "description": "Optional Graphiti node UUID to center the search.",
        },
        "entity_type_filter": {
            "type": "array",
            "description": "Optional Graphiti entity labels to filter.",
        },
        "as_of_in_game_time": {
            "type": "string",
            "description": "Optional ISO datetime for temporal search.",
        },
    }
    ingest_properties: dict[str, Any] = {
        "user_message": {
            "type": "string",
            "description": "Latest user message.",
        },
        "assistant_message": {
            "type": "string",
            "description": "Latest assistant reply.",
        },
        "message_index": {
            "type": "number",
            "description": "Optional turn/message number.",
        },
    }

    return [
        {
            "name": SEARCH_TOOL_NAME,
            "description": (
                "Search the Graphiti long-term memory graph for facts relevant to "
                "the current Marinara chat turn."
            ),
            "parametersSchema": {
                "type": "object",
                "properties": search_properties,
                "required": ["user_message"],
            },
            "executionType": "webhook",
            "webhookUrl": search_url,
            "staticResult": None,
            "scriptBody": None,
            "enabled": True,
        },
        {
            "name": INGEST_TOOL_NAME,
            "description": (
                "Store the latest Marinara turn in Graphiti long-term graph memory."
            ),
            "parametersSchema": {
                "type": "object",
                "properties": ingest_properties,
                "required": ["user_message", "assistant_message"],
            },
            "executionType": "webhook",
            "webhookUrl": ingest_url,
            "staticResult": None,
            "scriptBody": None,
            "enabled": True,
        },
    ]


def build_agents(connection_id: str) -> list[dict[str, Any]]:
    return [
        {
            "type": RETRIEVE_AGENT_TYPE,
            "name": "Graph Memory Retrieve",
            "description": "Retrieves relevant Graphiti memories before generation.",
            "phase": "pre_generation",
            "enabled": True,
            "connectionId": connection_id,
            "promptTemplate": SEARCH_PROMPT,
            "settings": {
                "resultType": "context_injection",
                "contextSize": 8,
                "maxTokens": 1024,
                "injectAsSection": True,
                "enabledTools": [SEARCH_TOOL_NAME],
            },
        },
        {
            "type": INGEST_AGENT_TYPE,
            "name": "Graph Memory Ingest",
            "description": "Stores completed turns in Graphiti after generation.",
            "phase": "post_processing",
            "enabled": True,
            "connectionId": connection_id,
            "promptTemplate": INGEST_PROMPT,
            "settings": {
                "resultType": "context_injection",
                "contextSize": 8,
                "maxTokens": 1024,
                "runInterval": 1,
                "enabledTools": [INGEST_TOOL_NAME],
                "includePreGenInjections": True,
                "includeParallelResults": True,
            },
        },
    ]


def find_by(items: list[dict[str, Any]], key: str, value: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get(key) == value), None)


def find_agent(items: list[dict[str, Any]], agent_type: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get("type") == agent_type), None)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
