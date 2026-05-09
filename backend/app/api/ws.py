from __future__ import annotations

import asyncio
import json
import logging
import time

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.settings import settings

router = APIRouter()
logger = logging.getLogger(__name__)

_SIGNAL_STREAM = "signals:broadcast"
_EXEC_STREAM = "executions:broadcast"
_STREAM_BLOCK_MS = 1000
_PING_INTERVAL = 30


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    r = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    tick_subscriptions: set[str] = set()   # "symbol:timeframe" keys
    last_signal_id = "$"
    last_exec_id = "$"

    async def read_client():
        """Handle messages from the frontend (subscribe/unsubscribe/ping)."""
        nonlocal tick_subscriptions
        try:
            while True:
                raw = await ws.receive_text()
                msg = json.loads(raw)
                mtype = msg.get("type")
                payload = msg.get("payload", {})

                if mtype == "subscribe_ticks":
                    symbol = payload.get("symbol", payload.get("asset_slug", ""))
                    tf = payload.get("timeframe", "")
                    if symbol and tf:
                        tick_subscriptions.add(f"{symbol}:{tf}")

                elif mtype == "unsubscribe_ticks":
                    symbol = payload.get("symbol", payload.get("asset_slug", ""))
                    tf = payload.get("timeframe", "")
                    tick_subscriptions.discard(f"{symbol}:{tf}")

                elif mtype == "ping":
                    await ws.send_text(json.dumps({"type": "pong", "ts": int(time.time()), "payload": {}}))

        except (WebSocketDisconnect, asyncio.CancelledError):
            pass

    async def stream_signals():
        """Forward signals and executions from Redis Streams."""
        nonlocal last_signal_id, last_exec_id
        while True:
            try:
                entries = await r.xread(
                    streams={_SIGNAL_STREAM: last_signal_id, _EXEC_STREAM: last_exec_id},
                    block=_STREAM_BLOCK_MS,
                    count=20,
                )
                for stream_name, messages in (entries or []):
                    for msg_id, fields in messages:
                        if stream_name == _SIGNAL_STREAM:
                            last_signal_id = msg_id
                            await ws.send_text(json.dumps({"type": "signal", "ts": int(time.time()), "payload": fields}))
                        elif stream_name == _EXEC_STREAM:
                            last_exec_id = msg_id
                            action = fields.get("action", "")
                            mtype = "execution" if action in ("open",) else "position_update"
                            await ws.send_text(json.dumps({"type": mtype, "ts": int(time.time()), "payload": fields}))
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("WebSocket stream error")
                await asyncio.sleep(1)

    async def stream_ticks():
        """
        Forward tick pub/sub messages for subscribed assets.
        Closed bars → type "tick"
        Live (unclosed) bars → type "live_tick"
        """
        pubsub = r.pubsub()
        await pubsub.subscribe("ticks:broadcast")
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                    symbol = data.get("symbol", data.get("asset_slug", ""))
                    key = f"{symbol}:{data.get('timeframe','')}"
                    if key in tick_subscriptions:
                        is_closed = data.get("is_closed", True)
                        msg_type = "tick" if is_closed else "live_tick"
                        await ws.send_text(json.dumps({
                            "type": msg_type,
                            "ts": int(time.time()),
                            "payload": data,
                        }))
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe("ticks:broadcast")
            await pubsub.aclose()

    async def ping_loop():
        while True:
            await asyncio.sleep(_PING_INTERVAL)
            try:
                await ws.send_text(json.dumps({"type": "pong", "ts": int(time.time()), "payload": {}}))
            except Exception:
                break

    tasks = [
        asyncio.create_task(read_client()),
        asyncio.create_task(stream_signals()),
        asyncio.create_task(stream_ticks()),
        asyncio.create_task(ping_loop()),
    ]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        await r.aclose()
        logger.info("WebSocket connection closed")
