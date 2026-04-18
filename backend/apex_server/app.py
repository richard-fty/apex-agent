"""FastAPI app factory for the apex agent server."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from apex_server.deps import AppState, build_default_app_state
from apex_server.routes.auth_routes import limiter as auth_limiter
from apex_server.routes.auth_routes import router as auth_router
from apex_server.routes.sessions_routes import router as sessions_router
from apex_server.routes.skills_routes import router as skills_router


def create_app(state: AppState | None = None) -> FastAPI:
    """Build a FastAPI app. Pass a custom `state` for tests."""

    app = FastAPI(title="Apex Agent", version="0.1.0")

    # Singletons for the lifetime of the process.
    app.state.app_state = state or build_default_app_state()

    # CORS: permissive for local dev; tighten for production deploys.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",  # Vite dev default
            "http://localhost:3000",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limit on /auth/login.
    app.state.limiter = auth_limiter
    app.add_middleware(SlowAPIMiddleware)

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(request, exc):  # pragma: no cover - trivial
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests"},
        )

    app.include_router(auth_router)
    app.include_router(sessions_router)
    app.include_router(skills_router)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


# Note: do NOT instantiate `app` at module import. Uvicorn launches the app
# via `create_app` using `--factory`, so the default SQLite connection is
# only opened when a real server starts — not during pytest collection or
# `python -c "import apex_server.app"`.

