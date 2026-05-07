from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, model_validator

from app.services.exchange_account_service import ExchangeAccountService

router = APIRouter()
_svc = ExchangeAccountService()


class ExchangeAccountCreate(BaseModel):
    name: str
    exchange: str
    is_paper: bool = False
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    description: Optional[str] = None

    @model_validator(mode="after")
    def require_credentials_for_live(self):
        if not self.is_paper and (not self.api_key or not self.api_secret):
            raise ValueError("api_key and api_secret are required for live accounts")
        return self


class ExchangeAccountUpdate(BaseModel):
    name: Optional[str] = None
    exchange: Optional[str] = None
    is_paper: Optional[bool] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    description: Optional[str] = None


async def _serialize(account, preview_key: bool = True):
    data = {
        "id": account.id,
        "name": account.name,
        "exchange": account.exchange,
        "is_paper": account.is_paper,
        "description": account.description,
        "created_at": account.created_at.isoformat() if account.created_at else None,
        "updated_at": account.updated_at.isoformat() if account.updated_at else None,
    }
    if preview_key and not account.is_paper:
        data["api_key_preview"] = await _svc.preview_key(account)
    else:
        data["api_key_preview"] = None
    return data


@router.get("/")
async def list_exchange_accounts():
    accounts = await _svc.list_all()
    return [await _serialize(a) for a in accounts]


@router.post("/", status_code=201)
async def create_exchange_account(body: ExchangeAccountCreate):
    account = await _svc.create(
        name=body.name,
        exchange=body.exchange,
        is_paper=body.is_paper,
        api_key=body.api_key,
        api_secret=body.api_secret,
        description=body.description,
    )
    return await _serialize(account)


@router.get("/{account_id}")
async def get_exchange_account(account_id: str):
    try:
        account = await _svc.get_by_id(account_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found")
    return await _serialize(account)


@router.put("/{account_id}")
async def update_exchange_account(account_id: str, body: ExchangeAccountUpdate):
    try:
        account = await _svc.update(
            account_id=account_id,
            name=body.name,
            exchange=body.exchange,
            is_paper=body.is_paper,
            api_key=body.api_key,
            api_secret=body.api_secret,
            description=body.description,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return await _serialize(account)


@router.delete("/{account_id}", status_code=204)
async def delete_exchange_account(account_id: str):
    try:
        await _svc.delete(account_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
