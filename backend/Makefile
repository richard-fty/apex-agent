HOST ?= 127.0.0.1
PORT ?= 8765

.PHONY: dev run test lint

# Hot-reloading dev server (like `gin` or `go run` loop). Run this and edit
# code — uvicorn reloads on save. Browse http://127.0.0.1:8765/docs.
dev:
	uv run uvicorn --factory apex_server.app:create_app --host $(HOST) --port $(PORT) --reload

# Production-style start — no reload, workers configurable.
run:
	uv run uvicorn --factory apex_server.app:create_app --host $(HOST) --port $(PORT)

# Run backend test suite.
test:
	uv run pytest tests/

# Run with APEX_DEV_BYPASS_AUTH=1 (skips login so you can hit the API directly).
dev-bypass:
	APEX_DEV_BYPASS_AUTH=1 uv run uvicorn --factory apex_server.app:create_app --host $(HOST) --port $(PORT) --reload
