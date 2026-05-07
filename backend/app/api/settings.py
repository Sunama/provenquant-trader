from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from app.db.models.app_setting import AppSetting
from app.db.session import SessionLocal
from app.services.exchange_account_service import ExchangeAccountService

router = APIRouter()
_svc = ExchangeAccountService()


async def get_db():
    async with SessionLocal() as db:
        yield db


async def _get_setting(db: AsyncSession, key: str) -> str | None:
    row = await db.get(AppSetting, key)
    return row.value if row else None


async def _set_setting(db: AsyncSession, key: str, value: str) -> None:
    stmt = insert(AppSetting).values(key=key, value=value)
    stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value": value})
    await db.execute(stmt)
    await db.commit()


class ProvenQuantSettings(BaseModel):
    api_url: str = ""
    api_key: str = ""


@router.get("/provenquant")
async def get_provenquant_settings(db: AsyncSession = Depends(get_db)):
    api_url = await _get_setting(db, "provenquant_api_url") or ""
    api_key_raw = await _get_setting(db, "provenquant_api_key") or ""
    masked = f"{api_key_raw[:4]}{'*' * max(0, len(api_key_raw) - 8)}{api_key_raw[-4:]}" if len(api_key_raw) > 8 else "*" * len(api_key_raw)
    return {"api_url": api_url, "api_key_preview": masked}


@router.put("/provenquant")
async def update_provenquant_settings(body: ProvenQuantSettings, db: AsyncSession = Depends(get_db)):
    await _set_setting(db, "provenquant_api_url", body.api_url)
    await _set_setting(db, "provenquant_api_key", body.api_key)
    return {"status": "ok"}


@router.get("/system")
async def get_system_status(db: AsyncSession = Depends(get_db)):
    import redis.asyncio as aioredis
    from app.core.settings import settings as app_settings

    redis_ok = False
    try:
        r = await aioredis.from_url(app_settings.REDIS_URL, decode_responses=True)
        await r.ping()
        await r.aclose()
        redis_ok = True
    except Exception:
        pass

    db_ok = False
    try:
        await db.execute(__import__("sqlalchemy").text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    return {"redis_connected": redis_ok, "db_connected": db_ok}
