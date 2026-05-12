from __future__ import annotations

import importlib
import os
import pkgutil
import uuid
from typing import Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.core.settings import settings
from app.db.models.strategy_asset import StrategyAsset
from app.db.models.strategy_config import StrategyConfig
from app.db.models.strategy_exchange_ref import StrategyExchangeRef
from app.db.session import SessionLocal
from app.services.internal_data_fetcher import InternalDataFetcher
from app.services.strategy_executer import StrategyExecuter
from app.services.symbol_validator import validate_symbol

router = APIRouter()


async def get_db():
    async with SessionLocal() as db:
        yield db


# ── Pydantic schemas ─────────────────────────────────────────

class StrategyAssetIn(BaseModel):
    symbol: str
    exchange: str
    timeframe: str
    market_type: str
    tick_process: bool = False
    role: str = "primary"
    subscribe_depth: bool = False
    exchange_account_num: int = 0
    description: Optional[str] = None
    transaction_fee: float = 0.0002


class StrategyExchangeRefIn(BaseModel):
    exchange_account_id: str
    description: Optional[str] = None


class StrategyConfigCreate(BaseModel):
    name: str
    strategy_class: str
    description: Optional[str] = None
    enabled: bool = True
    is_paper: bool = True
    params: dict = {}
    parameters_schema: Optional[list] = None
    signal_definitions: Optional[list] = None
    base_asset: Optional[str] = None
    assets: list[StrategyAssetIn] = []
    exchange_accounts: list[StrategyExchangeRefIn] = []


class StrategyConfigUpdate(BaseModel):
    name: Optional[str] = None
    strategy_class: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    is_paper: Optional[bool] = None
    params: Optional[dict] = None
    parameters_schema: Optional[list] = None
    signal_definitions: Optional[list] = None
    base_asset: Optional[str] = None
    assets: Optional[list[StrategyAssetIn]] = None
    exchange_accounts: Optional[list[StrategyExchangeRefIn]] = None


def _serialize(config: StrategyConfig) -> dict:
    return {
        "id": config.id,
        "name": config.name,
        "strategy_class": config.strategy_class,
        "description": config.description,
        "enabled": config.enabled,
        "is_paper": config.is_paper,
        "params": config.params,
        "parameters_schema": config.parameters_schema,
        "signal_definitions": config.signal_definitions,
        "base_asset": config.base_asset,
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
        "assets": [
            {
                "leg_num": a.leg_num,
                "role": a.role,
                "symbol": a.symbol,
                "exchange": a.exchange,
                "timeframe": a.timeframe,
                "market_type": a.market_type,
                "tick_process": a.tick_process,
                "subscribe_depth": a.subscribe_depth,
                "exchange_account_num": a.exchange_account_num,
                "description": a.description,
                "base_asset": a.base_asset,
                "quote_asset": a.quote_asset,
                "transaction_fee": a.transaction_fee,
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


async def _notify_trader() -> None:
    r = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    await r.publish("strategy:config_changed", "")
    await r.aclose()


async def _validate_assets(assets: list[StrategyAssetIn]) -> dict[int, tuple[str, str]]:
    """Validate all asset symbols. Returns {index: (base_asset, quote_asset)} on success."""
    result: dict[int, tuple[str, str]] = {}
    for i, asset in enumerate(assets):
        info = await validate_symbol(asset.symbol, asset.exchange, asset.market_type)
        if info is None:
            raise HTTPException(
                status_code=422,
                detail=f"Asset #{i}: symbol '{asset.symbol}' not found on {asset.exchange} {asset.market_type}",
            )
        result[i] = (info.base_asset, info.quote_asset)
    return result


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
                        default_subs = [
                            {
                                "symbol": s.symbol,
                                "exchange": s.exchange,
                                "timeframe": s.timeframe,
                                "market_type": s.market_type,
                                "tick_process": s.tick_process,
                                "subscribe_depth": s.subscribe_depth,
                                "description": s.description,
                            }
                            for s in instance.subscriptions
                        ]
                        classes.append({"class_path": class_path, "id": instance.id, "parameter_schema": schema, "default_subscriptions": default_subs})
                    except Exception:
                        classes.append({"class_path": class_path, "id": None, "parameter_schema": [], "default_subscriptions": []})
        except Exception:
            pass
    return classes


@router.get("/validate-symbol")
async def validate_symbol_endpoint(
    symbol: str,
    exchange: str = "binance",
    market_type: str = "futures",
):
    """Check whether a symbol exists on an exchange and return its base/quote assets."""
    info = await validate_symbol(symbol, exchange, market_type)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found on {exchange} {market_type}")
    return {"symbol": info.symbol, "base_asset": info.base_asset, "quote_asset": info.quote_asset}


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
            {
                "symbol": s.symbol,
                "exchange": s.exchange,
                "timeframe": s.timeframe,
                "market_type": s.market_type,
                "tick_process": s.tick_process,
                "subscribe_depth": s.subscribe_depth,
                "description": s.description,
            }
            for s in instance.subscriptions
        ] if hasattr(instance, "subscriptions") else []
        return {"id": instance.id, "parameter_schema": schema, "subscriptions_template": subs}
    except (ImportError, AttributeError) as e:
        raise HTTPException(status_code=404, detail=f"Cannot import: {e}")


@router.get("/{strategy_id}/indicators")
async def get_strategy_indicators(
    strategy_id: str,
    symbol: str,
    timeframe: str,
    limit: int = Query(default=200, le=500),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(StrategyConfig).where(StrategyConfig.id == strategy_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        module_path, class_name = config.strategy_class.rsplit(".", 1)
        module = importlib.import_module(module_path)
        strategy = getattr(module, class_name)(params=config.params)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot load strategy: {e}")

    klines = await InternalDataFetcher().get_klines(symbol, timeframe, limit=limit)
    return [s.to_dict() for s in strategy.indicators(klines)]


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
    asset_info = await _validate_assets(body.assets)

    new_id = str(uuid.uuid4())
    config = StrategyConfig(
        id=new_id,
        name=body.name,
        strategy_class=body.strategy_class,
        description=body.description,
        enabled=body.enabled,
        is_paper=body.is_paper,
        params=body.params or {},
        parameters_schema=body.parameters_schema,
        signal_definitions=body.signal_definitions,
        base_asset=body.base_asset,
    )
    db.add(config)

    for i, asset_in in enumerate(body.assets):
        base_asset, quote_asset = asset_info[i]
        db.add(StrategyAsset(
            strategy_id=new_id,
            leg_num=i,
            role=asset_in.role,
            symbol=asset_in.symbol,
            exchange=asset_in.exchange,
            timeframe=asset_in.timeframe,
            market_type=asset_in.market_type,
            tick_process=asset_in.tick_process,
            subscribe_depth=asset_in.subscribe_depth,
            exchange_account_num=asset_in.exchange_account_num,
            description=asset_in.description,
            base_asset=base_asset,
            quote_asset=quote_asset,
            transaction_fee=asset_in.transaction_fee,
        ))

    for i, ref_in in enumerate(body.exchange_accounts):
        db.add(StrategyExchangeRef(
            strategy_id=new_id,
            exchange_num=i,
            exchange_account_id=ref_in.exchange_account_id,
            description=ref_in.description,
        ))

    await db.commit()
    await _notify_trader()
    return {"id": config.id, "name": config.name}


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

    if body.name is not None:
        config.name = body.name
    if body.strategy_class is not None:
        config.strategy_class = body.strategy_class
    if body.description is not None:
        config.description = body.description
    if body.enabled is not None:
        config.enabled = body.enabled
    if body.is_paper is not None:
        config.is_paper = body.is_paper
    if body.params is not None:
        config.params = body.params
    if body.parameters_schema is not None:
        config.parameters_schema = body.parameters_schema
    if body.signal_definitions is not None:
        config.signal_definitions = body.signal_definitions
    if body.base_asset is not None:
        config.base_asset = body.base_asset

    if body.assets is not None:
        asset_info = await _validate_assets(body.assets)
        for asset in config.assets:
            await db.delete(asset)
        for i, asset_in in enumerate(body.assets):
            base_asset, quote_asset = asset_info[i]
            db.add(StrategyAsset(
                strategy_id=strategy_id,
                leg_num=i,
                role=asset_in.role,
                symbol=asset_in.symbol,
                exchange=asset_in.exchange,
                timeframe=asset_in.timeframe,
                market_type=asset_in.market_type,
                tick_process=asset_in.tick_process,
                subscribe_depth=asset_in.subscribe_depth,
                exchange_account_num=asset_in.exchange_account_num,
                description=asset_in.description,
                base_asset=base_asset,
                quote_asset=quote_asset,
                transaction_fee=asset_in.transaction_fee,
            ))

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
    await _notify_trader()
    return {"id": config.id}


@router.delete("/{strategy_id}", status_code=204)
async def delete_strategy(strategy_id: str, db: AsyncSession = Depends(get_db)):
    config = await db.get(StrategyConfig, strategy_id)
    if not config:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(config)
    await db.commit()
    await _notify_trader()


@router.patch("/{strategy_id}/toggle")
async def toggle_strategy(strategy_id: str, db: AsyncSession = Depends(get_db)):
    config = await db.get(StrategyConfig, strategy_id)
    if not config:
        raise HTTPException(status_code=404, detail="Not found")
    config.enabled = not config.enabled
    await db.commit()
    await _notify_trader()
    return {"id": config.id, "enabled": config.enabled}
