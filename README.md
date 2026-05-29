# Marinara Graphiti

This repository contains the standalone Graphiti memory service for Marinara, plus Docker packaging, smoke-test scripts, and Marinara custom tool/agent registration helpers.

## What is included

- `docker-compose.yml` for Neo4j 5.21+ and `graphiti-api`
- FastAPI wrapper under `graphiti-api/src/`
- `graphiti-api/Dockerfile` and dependency pins for `graphiti-core==0.29.1`
- `.env.example` with practical defaults
- Windows helper scripts in `scripts/`
- Marinara registration helper in `scripts/register-marinara-integration.py`

## Prerequisites

- Windows 11 with Docker Desktop installed
- WSL2 enabled with Docker Desktop WSL integration
- Marinara Engine running on Windows and reachable at `http://localhost:7860`
- A valid OpenRouter API key in `DEEPSEEK_API_KEY`
- `python3` available in WSL for the smoke test
- Neo4j 5.26+ via Docker, which satisfies the Graphiti 5.21+ floor and matches the current docs

## Setup

1. Copy `.env.example` to `.env`.
2. Fill in `NEO4J_PASSWORD`.
3. Add your OpenRouter API key as `DEEPSEEK_API_KEY`.
4. Confirm Marinara can be reached from WSL at `http://localhost:7860`.

The compose file uses `host.docker.internal:7860` so the container can reach Marinara on the Windows host.
The default LLM endpoint is OpenRouter using `deepseek/deepseek-v3.2`.
The default embedding endpoint is OpenRouter using `qwen/qwen3-embedding-8b` with dimension `4096`.

## Start

From the repo root:

```bat
scripts\start.bat
```

Or from WSL:

```bash
docker compose up -d --build
```

Neo4j is published on `http://localhost:7474` and Graphiti API on `http://localhost:8765`.

## Stop

```bat
scripts\stop.bat
```

Or from WSL:

```bash
docker compose down
```

## Reset the graph

This clears Neo4j data while keeping the schema in place:

```bat
scripts\reset-graph.bat
```

## Smoke test

After the stack is up, run:

```bash
python3 scripts/test-roundtrip.py
```

The script:

1. Calls `GET /health`
2. Posts five synthetic episodes to `POST /episodes/add`
3. Polls `POST /search` for the expected round-trip facts

## Marinara agent import

For local WSL/Docker webhooks, add this line to the Marinara Engine `.env` on Windows:

```env
WEBHOOK_LOCAL_URLS_ENABLED=true
```

Marinara hot-reloads this setting within a few seconds. Without it, custom tool webhooks using `http://localhost:8765` are rejected by the server-side outbound URL policy.

Register or update the Graphiti custom tools and custom agents through the Marinara API:

```bash
python3 scripts/register-marinara-integration.py
```

To also enable the integration on a specific chat:

```bash
python3 scripts/register-marinara-integration.py --chat-id <marinara-chat-id>
```

When `--chat-id` is provided, the script only enables the Graphiti agents on that chat. The custom tools stay global; Marinara sends the active chat id in the custom tool webhook `context.chatId` field.

The chat metadata must use:

- `enableAgents: true`
- `enableTools: false`
- `activeAgentIds`: `custom-graph-memory-ingest`, `custom-graph-memory-retrieve`
- `activeToolIds`: `[]`

The Graphiti tools are enabled inside each custom agent's `enabledTools` settings. Keeping chat-level `enableTools` disabled prevents the main roleplay model from calling memory tools directly in the middle of narration.

The webhook targets are:

- `http://localhost:8765/tools/ingest`
- `http://localhost:8765/tools/search`

The Graphiti API also accepts legacy `?chat_id=<marinara-chat-id>` webhook URLs, but this should only be used with older Marinara builds that do not send custom tool webhook context.

## Memory boundaries with Marinara native agents

Graphiti should not duplicate data already produced by Marinara's native tracker and writer agents. Keep these responsibilities separate:

- Marinara World State owns current date/time, weather, current location, and present characters.
- Character Tracker owns current mood, actions, appearance, outfit, thoughts, and per-character stats.
- Quest Tracker owns active objectives, progress, completion state, and rewards.
- Persona Stats owns player status bars and custom numeric stats.
- Background and Expression Engine own scene visuals.
- Writer agents own prose correction, continuity checks, narrative direction, and secret plot pacing.

Graphiti is for durable long-term memory only: significant past events, revelations, promises, secrets, durable relationships, betrayals, harms, deaths, notable artifacts, ownership of important items, faction membership, reputation, trauma, and facts that should survive across many turns.

For that reason the custom agents are thin wrappers:

- `graph_memory_search` receives the latest user message as `user_message`; the Python backend builds the Graphiti search query and filters transient tracker overlap.
- `graph_memory_ingest` receives only the latest user and assistant messages, plus optional technical metadata such as `message_index`; the Python backend stores the raw turn and lets Graphiti extract durable entities and relations.

Do not add World State, Character Tracker, Quest Tracker, Persona Stats, Background, Expression Engine, or writer-agent notes to the Graphiti webhook body. If a future Marinara update resets the custom agents, keep the prompts in `scripts/register-marinara-integration.py` aligned with this boundary.

## Marinara custom tool context patch

This integration expects a small Marinara server patch so custom tool webhooks receive the active chat id automatically.

In `packages/server/src/services/tools/tool-executor.ts`:

- Add `chatId?: string` to `ToolExecutionContext`.
- Pass the full tool execution context into `executeCustomTool`.
- For webhook custom tools, send:

```json
{
  "tool": "tool_name",
  "arguments": {},
  "context": {
    "chatId": "active-marinara-chat-id"
  }
}
```

In `packages/server/src/routes/generate.routes.ts`, add `chatId: input.chatId` to `baseToolExecutionContext`.

With this patch, the Graphiti tools can be registered once as global custom tools. Any chat only needs `custom-graph-memory-retrieve` and `custom-graph-memory-ingest` enabled; Graphiti uses `context.chatId` as its memory `group_id`.

## Runtime notes

`GET /health` returns `503 degraded` until Neo4j, OpenRouter LLM, and OpenRouter embeddings are all reachable.
The custom agents use the configured Marinara connection for agent calls; the current default registration uses OpenRouter `deepseek/deepseek-v3.2`.

## Validation so far

- Docker Compose config renders successfully.
- `graphiti-api` image builds successfully.
- The API imports correctly inside the container.
- With Neo4j running through Compose, `/health` reports `neo4j: connected`.
- Full synthetic ingest/search passes through `scripts/test-roundtrip.py`.
- Marinara custom agents fire during roleplay generation when both agents and tools are enabled on the chat.
