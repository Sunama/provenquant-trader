"""
API tests for /api/exchange-accounts endpoints.
Tests use paper accounts (is_paper=True) to avoid pgcrypto dependency.
"""
from __future__ import annotations

import pytest

from tests.test_api.conftest import needs_db

pytestmark = [pytest.mark.integration, needs_db]

_PAPER_BODY = {
    "name": "My Paper Account",
    "exchange": "binance",
    "is_paper": True,
}

_LIVE_BODY = {
    "name": "My Live Account",
    "exchange": "binance",
    "is_paper": False,
    "api_key": "fake-api-key-1234",
    "api_secret": "fake-api-secret-5678",
}


# ── GET /api/exchange-accounts/ ──────────────────────────────────────────────

async def test_list_accounts_empty(client):
    r = await client.get("/api/exchange-accounts/")
    assert r.status_code == 200
    assert r.json() == []


async def test_list_accounts_returns_all(client):
    await client.post("/api/exchange-accounts/", json=_PAPER_BODY)
    await client.post("/api/exchange-accounts/", json={**_PAPER_BODY, "name": "Second"})

    r = await client.get("/api/exchange-accounts/")
    assert r.status_code == 200
    assert len(r.json()) == 2


# ── POST /api/exchange-accounts/ ─────────────────────────────────────────────

async def test_create_paper_account(client):
    r = await client.post("/api/exchange-accounts/", json=_PAPER_BODY)
    assert r.status_code == 201
    data = r.json()
    assert "id" in data
    assert data["name"] == "My Paper Account"
    assert data["exchange"] == "binance"
    assert data["is_paper"] is True
    assert data["api_key_preview"] is None


async def test_create_live_account_missing_credentials_returns_422(client):
    """Live account without api_key/api_secret must fail validation."""
    r = await client.post("/api/exchange-accounts/", json={
        "name": "Live No Creds",
        "exchange": "binance",
        "is_paper": False,
    })
    assert r.status_code == 422


async def test_create_account_response_schema(client):
    r = await client.post("/api/exchange-accounts/", json=_PAPER_BODY)
    assert r.status_code == 201
    data = r.json()
    for field in ("id", "name", "exchange", "is_paper", "description", "created_at", "updated_at"):
        assert field in data


# ── GET /api/exchange-accounts/{id} ─────────────────────────────────────────

async def test_get_account_not_found(client):
    r = await client.get("/api/exchange-accounts/nonexistent")
    assert r.status_code == 404


async def test_get_account(client):
    create_r = await client.post("/api/exchange-accounts/", json=_PAPER_BODY)
    account_id = create_r.json()["id"]

    r = await client.get(f"/api/exchange-accounts/{account_id}")
    assert r.status_code == 200
    assert r.json()["id"] == account_id
    assert r.json()["name"] == "My Paper Account"


# ── PUT /api/exchange-accounts/{id} ─────────────────────────────────────────

async def test_update_account_name(client):
    create_r = await client.post("/api/exchange-accounts/", json=_PAPER_BODY)
    account_id = create_r.json()["id"]

    r = await client.put(
        f"/api/exchange-accounts/{account_id}",
        json={"name": "Renamed Account"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed Account"


async def test_update_account_not_found(client):
    r = await client.put("/api/exchange-accounts/nonexistent", json={"name": "X"})
    assert r.status_code == 404


async def test_update_description(client):
    create_r = await client.post("/api/exchange-accounts/", json=_PAPER_BODY)
    account_id = create_r.json()["id"]

    r = await client.put(
        f"/api/exchange-accounts/{account_id}",
        json={"description": "A paper trading account"},
    )
    assert r.status_code == 200
    assert r.json()["description"] == "A paper trading account"


# ── DELETE /api/exchange-accounts/{id} ───────────────────────────────────────

async def test_delete_account(client):
    create_r = await client.post("/api/exchange-accounts/", json=_PAPER_BODY)
    account_id = create_r.json()["id"]

    r = await client.delete(f"/api/exchange-accounts/{account_id}")
    assert r.status_code == 204

    r2 = await client.get(f"/api/exchange-accounts/{account_id}")
    assert r2.status_code == 404


async def test_delete_nonexistent_account_is_silent(client):
    """DELETE on nonexistent account executes 0 rows but raises no error — idempotent."""
    r = await client.delete("/api/exchange-accounts/nonexistent")
    assert r.status_code == 204
