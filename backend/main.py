from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.db import base  # noqa: F401 — ensures models are registered with SQLAlchemy
from app.api import api_router
from app.api.ws import router as ws_router
from app.core.settings import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_STR}/openapi.json",
)

if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_STR)
app.include_router(ws_router)  # WebSocket at /ws (no prefix)


@app.get("/")
def root():
    return {"message": "ProvenQuant Trader API"}
