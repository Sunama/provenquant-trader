from __future__ import annotations

import importlib
import os
import pkgutil
from typing import Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.core.settings import settings
from app.db.models.strategy_asset import StrategyAsset
from app.db.models.strategy_config import StrategyConfig
from app.db.models.strategy_exchange_ref import StrategyExchangeRef
from app.db.session import SessionLocal
from app.services.strategy_executer import StrategyExecuter

router = APIRouter()


async def get_db():
    async with SessionLocal() as db:
        yield db


# ── Pydantic schemas ─────────────────────────────────────────

class StrategyAssetIn(BaseModel):
    asset_slug: str
    exchange: str
    timeframe: str
    market_type: str
    tick_process: bool = False
    description: Optional[str] = None


class StrategyExchangeRefIn(BaseModel):
    exchange_account_id: str
    description: Optional[str] = None


class StrategyConfigCreate(BaseModel):
    id: str
    strategy_class: str
    description: Optional[str] = None
    enabled: bool = True
    params: dict = {}
    parameters_schema: Optional[list] = None
    signal_definitions: Optional[list] = None
    assets: list[StrategyAssetIn] = []
    exchange_accounts: list[StrategyExchangeRefIn] = []


class StrategyConfigUpdate(BaseModel):
    strategy_class: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    params: Optional[dict] = None
    parameters_schema: Optional[list] = None
    signal_definitions: Optional[list] = None
    assets: Optional[list[StrategyAssetIn]] = None
    exchange_accounts: Optional[list[StrategyExchangeRefIn]] = None


def _serialize(config: StrategyConfig) -> dict:
    return {
        "id": config.id,
        "strategy_class": config.strategy_class,
        "description": config.description,
        "enabled": config.enabled,
        "params": config.params,
        "parameters_schema": config.parameters_schema,
        "signal_definitions": config.signal_definitions,
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
        "assets": [
            {
                "asset_num": a.asset_num,
                "asset_slug": a.asset_slug,
                "exchange": a.exchange,
                "timeframe": a.timeframe,
                "market_type": a.market_type,
                "tick_process": a.tick_process,
                "description": a.description,
            }
            for a in (config.assets or [])
        ],
        "exchange_accounts": [
            {
                "exchange_num": r.exchange_num,
                "exchange_account_id": r.exchange_account_id,
                "description": r.description,
            }
            for r in (config.exchange_refs or [])
        ],
    }


# ── Endpoints ─────────────────────────────────────────────────

@router.get("/")
async def list_strategies(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(StrategyConfig)
        .options(selectinload(StrategyConfig.assets), selectinload(StrategyConfig.exchange_refs))
    )
    return [_serialize(r) for r in result.scalars().all()]


@router.get("/classes")
async def list_strategy_classes():
    """Scan strategies/ directory and return all StrategyExecuter subclasses."""
    import sys
    strategies_path = os.path.join(os.path.dirname(__file__), "../../strategies")
    strategies_path = os.path.abspath(strategies_path)
    if not os.path.isdir(strategies_path):
        return []

    classes = []
    for finder, name, _ in pkgutil.iter_modules([strategies_path]):
        try:
            module = importlib.import_module(f"strategies.{name}")
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, StrategyExecuter)
                    and attr is not StrategyExecuter
                ):
                    class_path = f"strategies.{name}.{attr_name}"
                    try:
                        instance = attr()
                        schema = [s.__dict__ for s in instance.parameter_schema] if hasattr(instance, "parameter_schema") else []
                        classes.append({"class_path": class_path, "id": instance.id, "parameter_schema": schema})
                    except Exception:
                        classes.append({"class_path": class_path, "id": None, "parameter_schema": []})
        except Exception:
            pass
    return classes


@router.get("/schema")
async def get_strategy_schema(class_path: str):
    """Introspect a strategy class and return its parameter schema."""
    try:
        module_path, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        if not (isinstance(cls, type) and issubclass(cls, StrategyExecuter)):
            raise HTTPException(status_code=400, detail="Not a StrategyExecuter subclass")
        instance = cls()
        schema = [s.__dict__ for s in instance.parameter_schema] if hasattr(instance, "parameter_schema") else []
        subs = [
            {"asset_slug": s.asset_slug, "exchange": s.exchange, "timeframe": s.timeframe, "market_type": s.market_type, "tick_process": s.tick_process}
            for s in instance.subscriptions
        ] if hasattr(instance, "subscriptions") else []
        return {"id": instance.id, "parameter_schema": schema, "subscriptions_template": subs}
    except (ImportError, AttributeError) as e:
        raise HTTPException(status_code=404, detail=f"Cannot import: {e}")


@router.get("/{strategy_id}")
async def get_strategy(strategy_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(StrategyConfig)
        .where(StrategyConfig.id == strategy_id)
        .options(selectinload(StrategyConfig.assets), selectinload(StrategyConfig.exchange_refs))
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Not found")
    return _serialize(config)


@router.post("/", status_code=201)
async def create_strategy(body: StrategyConfigCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.get(StrategyConfig, body.id)
    if existing:
        raise HTTPException(status_code=409, detail="Strategy ID already exists")

    config = StrategyConfig(
        id=body.id,
        strategy_class=body.strategy_class,
        description=body.description,
        enabled=body.enabled,
        params=body.params or {},
        parameters_schema=body.parameters_schema,
        signal_definitions=body.signal_definitions,
    )
    db.add(config)

    for i, asset_in in enumerate(body.assets):
        db.add(StrategyAsset(
            strategy_id=body.id,
            asset_num=i,
            **asset_in.model_dump(),
        ))

    for i, ref_in in enumerate(body.exchange_accounts):
        db.add(StrategyExchangeRef(
            strategy_id=body.id,
            exchange_num=i,
            exchange_account_id=ref_in.exchange_account_id,
            description=ref_in.description,
        ))

    await db.commit()
    return {"id": config.id}


@router.put("/{strategy_id}")
async def update_strategy(strategy_id: str, body: StrategyConfigUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(StrategyConfig)
        .where(StrategyConfig.id == strategy_id)
        .options(selectinload(StrategyConfig.assets), selectinload(StrategyConfig.exchange_refs))
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Not found")

    if body.strategy_class is not None:
        config.strategy_class = body.strategy_class
    if body.description is not None:
        config.description = body.description
    if body.enabled is not None:
        config.enabled = body.enabled
    if body.params is not None:
        config.params = body.params
    if body.parameters_schema is not None:
        config.parameters_schema = body.parameters_schema
    if body.signal_definitions is not None:
        config.signal_definitions = body.signal_definitions

    if body.assets is not None:
        for asset in config.assets:
            await db.delete(asset)
        for i, asset_in in enumerate(body.assets):
            db.add(StrategyAsset(strategy_id=strategy_id, asset_num=i, **asset_in.model_dump()))

    if body.exchange_accounts is not None:
        for ref in config.exchange_refs:
            await db.delete(ref)
        for i, ref_in in enumerate(body.exchange_accounts):
            db.add(StrategyExchangeRef(
                strategy_id=strategy_id,
                exchange_num=i,
                exchange_account_id=ref_in.exchange_account_id,
                description=ref_in.description,
            ))

    await db.commit()
    return {"id": config.id}


@router.delete("/{strategy_id}", status_code=204)
async def delete_strategy(strategy_id: str, db: AsyncSession = Depends(get_db)):
    config = await db.get(StrategyConfig, strategy_id)
    if not config:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(config)
    await db.commit()


@router.patch("/{strategy_id}/toggle")
async def toggle_strategy(strategy_id: str, db: AsyncSession = Depends(get_db)):
    config = await db.get(StrategyConfig, strategy_id)
    if not config:
        raise HTTPException(status_code=404, detail="Not found")
    config.enabled = not config.enabled
    await db.commit()

    r = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    await r.publish("strategy:config_changed", "")
    await r.aclose()

    return {"id": config.id, "enabled": config.enabled}
