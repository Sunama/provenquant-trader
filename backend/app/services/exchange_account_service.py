from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text, select, delete

from app.core.settings import settings
from app.db.models.exchange_account import ExchangeAccount
from app.db.models.strategy_exchange_ref import StrategyExchangeRef
from app.db.session import SessionLocal


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
