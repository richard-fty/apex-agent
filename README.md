# Apex Agent

A general-purpose autonomous agent platform with a runtime-first architecture: composable execution, explicit tool boundaries, dynamic tool visibility, and fail-closed defaults. Ships with a benchmark harness, a pluggable skill system, and a terminal UI.

## Architecture

```
 ┌─ TUI / CLI / Harness ─┐
 │                       │
 ▼                       ▼
Session (state, approvals, cost)
 │
 ▼
Turn Orchestrator ──→ LLM (LiteLLM)
 │
 ├── Tool Dispatch ─── Tools (filesystem, shell, web, rag)
 ├── Skill Loader  ─── Skills (domain-specific, auto-surfacing)
 ├── Context Assembler (system + skills + retrieval + history)
 └── Sandbox / Managed Runtime
```

Design principles are enumerated in [doc/design-checklist.md](doc/design-checklist.md); the full design spec lives in [doc/design-spec.md](doc/design-spec.md).

## Features

- **Multi-provider LLM**: Anthropic, OpenAI, Google, DeepSeek via LiteLLM
- **Tool system**: filesystem, shell, web search, RAG — each with access-control metadata and approval policies
- **Skill framework**: pluggable domain skills with intent-based pre-loading
- **RAG integration**: semantic search via standalone [rag-service](https://github.com/richard-fty/rag-service) (vector / BM25 / hybrid)
- **Benchmark harness**: scenario-based agent evaluation with metrics, cost tracking, and comparison reports
- **Terminal UI**: Textual-based TUI with live trace, approvals, and session controls
- **Context engineering**: layered assembly (system → skills → retrieval → compressed history → recent turns)
- **Permission policies**: `allow` / `ask` / `deny` with resumable approvals and permission modes

## Quick Start

```bash
uv sync
cp .env.example .env
# Add API keys (at minimum DEEPSEEK_API_KEY for the default model)

# Start Postgres
docker compose up -d postgres

# TUI
uv run python -m tui

# CLI
uv run python main.py

# Eval suite
uv run python -m eval
```

## Local Postgres

The repo now uses Postgres for session, auth, and wealth storage. A minimal
local database is provided via `docker-compose.yml`.

```bash
docker compose up -d postgres
docker compose ps
```

What it does:

- starts a local `postgres:16-alpine` container
- creates a database using `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB`
- exposes Postgres on `localhost:${POSTGRES_PORT}`
- stores DB data in the named volume `apex_postgres_data`
- waits until Postgres is healthy via `pg_isready`

The matching local connection string lives in `.env.example` as:

```bash
DATABASE_URL=postgresql://apex:apex_dev_password@localhost:5432/apex_agent
```

Useful commands:

```bash
docker compose up -d postgres
docker compose logs -f postgres
docker compose stop postgres
docker compose down
```

## Project Structure

```
core/
  src/
    agent/        # import package: models, runtime, session, policy, skills, context, artifacts, events
    tools/        # filesystem, shell, web, rag, skill_meta — hands exposed to the brain
    skill_packs/  # pluggable domain packs (e.g., stock_strategy) — content
    services/     # retrieval policy, search orchestrator, web search — harness-side services
    scenarios/    # eval scenarios (core_agent, stock_strategy)
    eval/         # eval runner, metrics, comparator, report, mock_mode
  tests/          # pytest suite for the core member
  main.py         # CLI entrypoint
  config.py       # shared settings
backend/          # FastAPI server
tui/              # Terminal UI (Textual)
frontend/         # Vite/React web client
doc/              # design spec, eval suite, design checklist
.codex/           # contributor guidance (AGENTS.md) — local-only
```

## Configuration

Set via environment variables or `.env`:

| Variable | Required | Description |
|----------|----------|-------------|
| `DEEPSEEK_API_KEY` | Yes (default model) | DeepSeek API key |
| `ANTHROPIC_API_KEY` | For Claude models | Anthropic API key |
| `OPENAI_API_KEY` | For GPT models | OpenAI API key |
| `SILICONFLOW_API_KEY` | For RAG | SiliconFlow API key (free tier available) |
| `TAVILY_API_KEY` | For web search | Tavily API key |

See [.env.example](.env.example) for all options.

## RAG Integration

RAG is powered by [rag-service](https://github.com/richard-fty/rag-service), a standalone retrieval service decoupled from this project:

- Multi-mode retrieval (vector, BM25, hybrid with RRF fusion)
- SiliconFlow embeddings (BAAI/bge-m3) with HuggingFace fallback
- API reranking (bge-reranker-v2-m3)
- BEIR/SciFact benchmark suite

## Benchmarks

Scenarios live in `scenarios/`. Each defines setup, expected behavior, and an evaluator. Run the full suite with `uv run python -m harness`. Evaluation design: [doc/eval-suite.md](doc/eval-suite.md).

## Supported Models

| Provider | Models |
|----------|--------|
| DeepSeek | `deepseek-chat`, `deepseek-reasoner` |
| Anthropic | `claude-sonnet-4`, `claude-haiku-4.5`, `claude-opus-4` |
| OpenAI | `gpt-4o`, `gpt-4o-mini` |
| Google | `gemini-1.5-pro`, `gemini-1.5-flash` |

## Contributing

Agent-collaboration conventions are in [.codex/AGENTS.md](.codex/AGENTS.md). New features should be reviewed against [doc/design-checklist.md](doc/design-checklist.md).
