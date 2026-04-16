# Apex Agent

A general-purpose autonomous agent platform with tool execution, skill system, benchmark harness, and terminal UI.

## Architecture

```
User ──→ TUI (Textual) ──→ Agent Loop ──→ LLM (LiteLLM)
                               │
                     ┌─────────┼─────────┐
                     ▼         ▼         ▼
                  Tools     Skills    RAG Service
               (filesystem, (pluggable, (rag-service)
                shell, web)  domain-
                             specific)
```

## Features

- **Multi-provider LLM support**: Anthropic, OpenAI, Google, DeepSeek via LiteLLM
- **Tool system**: filesystem, shell, web search, RAG — with access control and approval policies
- **Skill framework**: pluggable domain skills (e.g., stock strategy analysis) with auto-loading
- **RAG integration**: semantic search via [rag-service](https://github.com/richard-fty/rag-service) (vector, BM25, hybrid)
- **Benchmark harness**: automated agent evaluation with metrics, cost tracking, and comparison reports
- **Terminal UI**: rich interactive TUI built with Textual
- **Context management**: configurable strategies (truncate, summary, tiered) for long conversations
- **Permission policies**: configurable access control for tools with approval workflows

## Quick Start

```bash
uv sync
cp .env.example .env
# Add API keys to .env (at minimum DEEPSEEK_API_KEY for the default model)

# Run the TUI
uv run python -m tui

# Run the agent in CLI mode
uv run python main.py

# Run benchmarks
uv run python -m harness
```

## Project Structure

```
agent/         # Core Apex Agent runtime, session, orchestration, context
harness/            # Benchmark runner, metrics, cost tracking, report generation
tools/              # Built-in tools: filesystem, shell, web, RAG wrapper
skills/             # Pluggable domain skills (e.g., stock_strategy)
services/           # Research orchestration, web search, retrieval policy
tui/                # Terminal UI (Textual-based)
tests/              # Pytest suite including RAG benchmarks
benchmarks/         # Standalone benchmark scripts and reports
```

## Configuration

Set via environment variables or `.env`:

| Variable | Required | Description |
|----------|----------|-------------|
| `DEEPSEEK_API_KEY` | Yes (default model) | DeepSeek API key |
| `ANTHROPIC_API_KEY` | For Claude models | Anthropic API key |
| `OPENAI_API_KEY` | For GPT models | OpenAI API key |
| `SILICONFLOW_API_KEY` | For RAG | SiliconFlow API key (free) |
| `TAVILY_API_KEY` | For web search | Tavily API key |

See [`.env.example`](.env.example) for all options.

## RAG Integration

RAG is powered by [rag-service](https://github.com/richard-fty/rag-service), a standalone retrieval service decoupled from this project. It provides:

- Multi-mode retrieval (vector, BM25, hybrid with RRF fusion)
- SiliconFlow embedding (BAAI/bge-m3) with HuggingFace fallback
- API reranking (bge-reranker-v2-m3)
- BEIR/SciFact benchmark suite

## Supported Models

| Provider | Models |
|----------|--------|
| DeepSeek | `deepseek-chat`, `deepseek-reasoner` |
| Anthropic | `claude-sonnet-4`, `claude-haiku-4.5`, `claude-opus-4` |
| OpenAI | `gpt-4o`, `gpt-4o-mini` |
| Google | `gemini-1.5-pro`, `gemini-1.5-flash` |
