from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text, select, delete

from app.core.settings import settings
from app.db.models.exchange_account import ExchangeAccount
from app.db.models.strategy_exchange_ref import StrategyExchangeRef
from app.db.session import SessionLocal
from app.services.trade_adapter import OrderRecord, PositionInfo

logger = logging.getLogger(__name__)


@dataclass
class DecryptedCredentials:
    api_key: str
    api_secret: str


class ExchangeAccountService:
    """CRUD for ExchangeAccount with pgcrypto transparent encryption."""

    async def create(
        self,
        name: str,
        exchange: str,
        is_paper: bool = False,
        api_key: str | None = None,
        api_secret: str | None = None,
        description: str | None = None,
    ) -> ExchangeAccount:
        if is_paper:
            async with SessionLocal() as session:
                account = ExchangeAccount(
                    name=name,
                    exchange=exchange,
                    is_paper=True,
                    api_key=None,
                    api_secret=None,
                    description=description,
                )
                session.add(account)
                await session.commit()
                await session.refresh(account)
                return account

        async with SessionLocal() as session:
            result = await session.execute(
                text("""
                    INSERT INTO exchange_accounts (name, exchange, is_paper, api_key, api_secret, description)
                    VALUES (
                        :name, :exchange, false,
                        pgp_sym_encrypt(:api_key, :secret),
                        pgp_sym_encrypt(:api_secret, :secret),
                        :description
                    )
                    RETURNING id
                """),
                {
                    "name": name,
                    "exchange": exchange,
                    "api_key": api_key,
                    "api_secret": api_secret,
                    "secret": settings.SERVER_SECRET,
                    "description": description,
                },
            )
            account_id = result.scalar_one()
            await session.commit()

        return await self.get_by_id(account_id)

    async def update(
        self,
        account_id: str,
        name: str | None = None,
        exchange: str | None = None,
        is_paper: bool | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        description: str | None = None,
    ) -> ExchangeAccount:
        async with SessionLocal() as session:
            result = await session.execute(
                select(ExchangeAccount).where(ExchangeAccount.id == account_id)
            )
            account = result.scalar_one_or_none()
            if not account:
                raise ValueError(f"ExchangeAccount {account_id} not found")

            if name is not None:
                account.name = name
            if exchange is not None:
                account.exchange = exchange
            if description is not None:
                account.description = description

            if is_paper is True:
                account.is_paper = True
                account.api_key = None
                account.api_secret = None
            elif is_paper is False:
                account.is_paper = False

            if not account.is_paper:
                if api_key is not None:
                    encrypted_key = (await session.execute(
                        text("SELECT pgp_sym_encrypt(:val, :secret)"),
                        {"val": api_key, "secret": settings.SERVER_SECRET},
                    )).scalar_one()
                    account.api_key = encrypted_key

                if api_secret is not None:
                    encrypted_secret = (await session.execute(
                        text("SELECT pgp_sym_encrypt(:val, :secret)"),
                        {"val": api_secret, "secret": settings.SERVER_SECRET},
                    )).scalar_one()
                    account.api_secret = encrypted_secret

            await session.commit()
            await session.refresh(account)
            return account

    async def delete(self, account_id: str) -> None:
        async with SessionLocal() as session:
            ref_count = (await session.execute(
                select(StrategyExchangeRef).where(
                    StrategyExchangeRef.exchange_account_id == account_id
                ).limit(1)
            )).scalar_one_or_none()
            if ref_count:
                raise ValueError("Cannot delete: account is referenced by an active strategy")

            await session.execute(
                delete(ExchangeAccount).where(ExchangeAccount.id == account_id)
            )
            await session.commit()

    async def get_by_id(self, account_id: str) -> ExchangeAccount:
        async with SessionLocal() as session:
            result = await session.execute(
                select(ExchangeAccount).where(ExchangeAccount.id == account_id)
            )
            account = result.scalar_one_or_none()
            if not account:
                raise ValueError(f"ExchangeAccount {account_id} not found")
            return account

    async def list_all(self) -> list[ExchangeAccount]:
        async with SessionLocal() as session:
            result = await session.execute(select(ExchangeAccount))
            return list(result.scalars().all())

    async def decrypt(self, account: ExchangeAccount) -> DecryptedCredentials:
        if account.is_paper:
            raise ValueError("Paper trade account has no API credentials")
        async with SessionLocal() as session:
            result = await session.execute(
                text("""
                    SELECT
                        pgp_sym_decrypt(api_key::bytea, :secret),
                        pgp_sym_decrypt(api_secret::bytea, :secret)
                    FROM exchange_accounts
                    WHERE id = :id
                """),
                {"id": account.id, "secret": settings.SERVER_SECRET},
            )
            row = result.one()
            return DecryptedCredentials(api_key=row[0], api_secret=row[1])

    async def preview_key(self, account: ExchangeAccount) -> str:
        if account.is_paper:
            return ""
        creds = await self.decrypt(account)
        key = creds.api_key
        if len(key) <= 8:
            return "*" * len(key)
        return f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"

    # ── Balance & order reading ───────────────────────────────────

    async def get_balances(self, account_id: str) -> dict[str, float]:
        """Return all non-zero asset balances for the account."""
        account = await self.get_by_id(account_id)
        if account.is_paper:
            from app.services.trade_adapter.paper import PaperTradeAdapter
            return await PaperTradeAdapter(config_id=account_id).get_all_balances()
        logger.warning(f"Live balance fetch not implemented for account {account_id}")
        return {}

    async def get_asset_balance(self, account_id: str, asset: str) -> float:
        """Return balance of a specific asset."""
        account = await self.get_by_id(account_id)
        if account.is_paper:
            from app.services.trade_adapter.paper import PaperTradeAdapter
            return await PaperTradeAdapter(config_id=account_id).get_asset_balance(asset)
        logger.warning(f"Live balance fetch not implemented for account {account_id}")
        return 0.0

    async def get_order_history(
        self, account_id: str, symbol: str, limit: int = 50
    ) -> list[OrderRecord]:
        """Return recent closed orders for symbol."""
        account = await self.get_by_id(account_id)
        if account.is_paper:
            from app.services.trade_adapter.paper import PaperTradeAdapter
            return await PaperTradeAdapter(config_id=account_id).get_order_history(symbol, limit)
        logger.warning(f"Live order history not implemented for account {account_id}")
        return []

    async def get_open_orders(self, account_id: str, symbol: str) -> list[OrderRecord]:
        """Return pending (unfilled) orders for symbol."""
        account = await self.get_by_id(account_id)
        if account.is_paper:
            import json
            from app.services.trade_adapter.paper import PaperTradeAdapter
            adapter = PaperTradeAdapter(config_id=account_id)
            r_client = await adapter._get_redis()
            order_ids = await r_client.smembers(adapter._pending_set())
            orders: list[OrderRecord] = []
            for oid in order_ids:
                raw = await r_client.get(adapter._pending_key(oid))
                if raw:
                    o = json.loads(raw)
                    if o.get("symbol") == symbol:
                        orders.append(OrderRecord(
                            order_id=oid,
                            symbol=o["symbol"],
                            side=o["side"],
                            order_type="limit",
                            price=float(o["limit_price"]),
                            size=float(o["size"]),
                            status="pending",
                            created_at=o.get("created_at", ""),
                        ))
            return orders
        logger.warning(f"Live open orders not implemented for account {account_id}")
        return []

    async def get_positions(self, account_id: str) -> list[PositionInfo]:
        """Return open positions (live only; paper positions are in the positions table)."""
        account = await self.get_by_id(account_id)
        if account.is_paper:
            return []
        logger.warning(f"Live positions not implemented for account {account_id}")
        return []
