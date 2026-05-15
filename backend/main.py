from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.cors import CORSMiddleware

from app.db import base  # noqa: F401 — ensures models are registered with SQLAlchemy
from app.api import api_router
from app.api.ws import router as ws_router
from app.core.auth import APIKeyMiddleware
from app.core.limiter import limiter
from app.core.settings import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_STR}/openapi.json",
)

# ── Rate limiting ──────────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Middleware (applied innermost → outermost; request traverses outermost first)
# Order here: CORSMiddleware wraps APIKeyMiddleware, so CORS headers appear on
# every response including 401s — browsers see correct CORS errors, not silent fails.

# Inner: auth — checks API key on protected routes
app.add_middleware(APIKeyMiddleware, api_key=settings.API_KEY)

# Outer: CORS — adds headers to ALL responses (including auth rejections)
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(api_router, prefix=settings.API_STR)
app.include_router(ws_router)  # WebSocket at /ws (no prefix)


@app.get("/")
def root():
    return {"message": "ProvenQuant Trader API"}
