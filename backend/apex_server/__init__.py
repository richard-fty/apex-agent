"""FastAPI server that exposes the agent runtime over HTTP + SSE."""

from apex_server.app import create_app

__all__ = ["create_app"]
