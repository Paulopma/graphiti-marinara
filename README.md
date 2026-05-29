# Marinara Graphiti

This repository contains the standalone Graphiti memory service for Marinara, plus Docker packaging, smoke-test scripts, and Marinara custom agent templates.

## What is included

- `docker-compose.yml` for Neo4j 5.21+ and `graphiti-api`
- FastAPI wrapper under `graphiti-api/src/`
- `graphiti-api/Dockerfile` and dependency pins for `graphiti-core==0.29.1`
- `.env.example` with practical defaults
- Windows helper scripts in `scripts/`
- Importable Marinara agent templates in `marinara-agents/`

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

Import the files in `marinara-agents/` into Marinara as custom agents:

- `ingest-agent.json` for the post-processing webhook
- `retrieve-agent.json` for the pre-generation context injection webhook
- `graphiti-bundle.json` as the combined bundle

The webhook targets are:

- `http://localhost:8765/episodes/add`
- `http://localhost:8765/search`

## Current blockers

These must be resolved before the integration can be exercised end-to-end:

- `DEEPSEEK_API_KEY` must contain a valid OpenRouter key for Graphiti extraction calls
- Marinara must be running on the Windows host at `http://localhost:7860`

`GET /health` returns `503 degraded` until Neo4j, OpenRouter LLM, and OpenRouter embeddings are all reachable.

## Validation so far

- Docker Compose config renders successfully.
- `graphiti-api` image builds successfully.
- The API imports correctly inside the container.
- With Neo4j running through Compose, `/health` reports `neo4j: connected`.
- Full round-trip ingest/search still requires a real OpenRouter key.

## Phase 2 notes

After the backend is live, import the two Marinara agents, enable turn data access for the ingest agent, and verify that the retrieve agent runs before the main model call while the ingest agent fires after the turn completes.
