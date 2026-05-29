SHELL := /usr/bin/env bash

COMPOSE ?= docker compose
GRAPHITI_URL ?= http://localhost:8765
MARINARA_URL ?= http://127.0.0.1:7860
CHAT_ID ?=

ifneq (,$(wildcard .env))
include .env
export
endif

.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo "Marinara Graphiti commands"
	@echo
	@echo "Stack:"
	@echo "  make up              Build and start Neo4j + graphiti-api"
	@echo "  make down            Stop the stack"
	@echo "  make restart         Restart the stack"
	@echo "  make build           Build images"
	@echo "  make rebuild-api     Rebuild and restart only graphiti-api"
	@echo "  make ps              Show container status"
	@echo
	@echo "Logs:"
	@echo "  make logs            Follow all logs"
	@echo "  make logs-api        Follow graphiti-api logs"
	@echo "  make logs-neo4j      Follow Neo4j logs"
	@echo
	@echo "Checks:"
	@echo "  make health          Call Graphiti /health"
	@echo "  make compile         Compile Python sources"
	@echo "  make smoke-test      Run scripts/test-roundtrip.py"
	@echo
	@echo "Marinara integration:"
	@echo "  make register        Register/update global tools and agents"
	@echo "  make register-chat CHAT_ID=<id>"
	@echo "                       Register/update and enable agents on a chat"
	@echo "  make register-dry-run"
	@echo "                       Print registration payload"
	@echo
	@echo "Data:"
	@echo "  make reset-graph     Delete all Neo4j graph data"

.PHONY: up
up:
	$(COMPOSE) up -d --build

.PHONY: down
down:
	$(COMPOSE) down

.PHONY: restart
restart: down up

.PHONY: build
build:
	$(COMPOSE) build

.PHONY: rebuild-api
rebuild-api:
	$(COMPOSE) up -d --build graphiti-api

.PHONY: ps
ps:
	$(COMPOSE) ps

.PHONY: logs
logs:
	$(COMPOSE) logs -f

.PHONY: logs-api
logs-api:
	$(COMPOSE) logs -f graphiti-api

.PHONY: logs-neo4j
logs-neo4j:
	$(COMPOSE) logs -f neo4j

.PHONY: health
health:
	@curl -sS "$(GRAPHITI_URL)/health" | python3 -m json.tool

.PHONY: compile
compile:
	python3 -m compileall graphiti-api/src scripts/register-marinara-integration.py

.PHONY: smoke-test
smoke-test:
	GRAPHITI_API_URL="$(GRAPHITI_URL)" python3 scripts/test-roundtrip.py

.PHONY: register
register:
	@python3 scripts/register-marinara-integration.py \
		--marinara-url "$(MARINARA_URL)" \
		--graphiti-url "$(GRAPHITI_URL)"

.PHONY: register-chat
register-chat:
	@if [[ -z "$(CHAT_ID)" ]]; then \
		echo "Usage: make register-chat CHAT_ID=<marinara-chat-id>"; \
		exit 2; \
	fi
	@python3 scripts/register-marinara-integration.py \
		--marinara-url "$(MARINARA_URL)" \
		--graphiti-url "$(GRAPHITI_URL)" \
		--chat-id "$(CHAT_ID)"

.PHONY: register-dry-run
register-dry-run:
	@python3 scripts/register-marinara-integration.py \
		--marinara-url "$(MARINARA_URL)" \
		--graphiti-url "$(GRAPHITI_URL)" \
		--dry-run

.PHONY: reset-graph
reset-graph:
	@if [[ -z "$${NEO4J_PASSWORD:-}" ]]; then \
		echo "NEO4J_PASSWORD was not found. Populate .env from .env.example first."; \
		exit 2; \
	fi
	$(COMPOSE) up -d neo4j
	$(COMPOSE) exec -T neo4j cypher-shell -u neo4j -p "$${NEO4J_PASSWORD}" "MATCH (n) DETACH DELETE n;"
