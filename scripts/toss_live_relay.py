#!/usr/bin/env python3
"""Read-only Toss WebSocket-to-SSE relay for the public briefing page.

The relay stays on loopback. A HTTPS tunnel can expose its two public routes:
`/healthz` and `/api/v1/live-stream`. OAuth credentials and raw Toss frames
never leave this process.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import random
from typing import Any
from zoneinfo import ZoneInfo

import websockets

from market_data.config import TossMarketConfig
from market_data.live_feed import LIVE_INSTRUMENTS, build_live_feed
from market_data.toss_client import TossMarketClient

KST = ZoneInfo("Asia/Seoul")
WS_URL = "wss://openapi-ws.tossinvest.com/ws/v1"
ALLOWED_ORIGIN = "https://js1876.github.io"
MAX_CLIENTS = 20
MACRO_INDICATORS = {"KOSPI": ("KOSPI", ""), "KOSDAQ": ("KOSDAQ", "")}


def now_iso() -> str:
    return datetime.now(KST).isoformat()


def build_macro_payload(client: TossMarketClient) -> dict[str, Any]:
    """Make a public macro snapshot; only public market endpoints are used."""
    prices = {item.symbol: float(item.last_price) for item in client.get_market_indicators(list(MACRO_INDICATORS))}
    items: list[dict[str, Any]] = []
    for symbol, (label, unit) in MACRO_INDICATORS.items():
        candles = client.get_market_indicator_candles(symbol, interval="1d", count=2)
        latest = prices.get(symbol, float(candles[0].close_price) if candles else 0.0)
        previous = float(candles[1].close_price) if len(candles) > 1 else latest
        change_pct = round(((latest - previous) / previous * 100) if previous else 0.0, 4)
        items.append({"id": symbol, "label": label, "value": latest, "unit": unit, "previousClose": previous, "changePct": change_pct, "asOf": now_iso(), "live": True})
    fx = client.get_exchange_rate("KRW", "USD")
    krw_per_usd = round(1 / float(fx["midRate"])) if float(fx["midRate"]) else 0.0
    items.append({"id": "USD_KRW", "label": "원/달러", "value": krw_per_usd, "unit": "원", "previousClose": None, "changePct": None, "asOf": fx.get("validFrom") or now_iso(), "live": True})
    bond = client.get_market_indicator_candles("KR_BOND_10Y", interval="1d", count=2)
    if bond:
        value = float(bond[0].close_price)
        previous = float(bond[1].close_price) if len(bond) > 1 else value
        items.append({"id": "KR_BOND_10Y", "label": "국고채 10년", "value": value, "unit": "%", "previousClose": previous, "changePct": round(((value - previous) / previous * 100) if previous else 0.0, 4), "asOf": bond[0].timestamp, "live": False})
    return {"generatedAt": now_iso(), "refreshSeconds": 5, "items": items}


def refresh_macro_payload(client: TossMarketClient, existing: dict[str, Any]) -> dict[str, Any]:
    """Refresh tick-like macro values without reloading slow daily reference data."""
    payload = deepcopy(existing)
    by_id = {item.get("id"): item for item in payload.get("items", []) if isinstance(item, dict)}
    prices = {item.symbol: float(item.last_price) for item in client.get_market_indicators(list(MACRO_INDICATORS))}
    for symbol, price in prices.items():
        item = by_id.get(symbol)
        if not item:
            continue
        previous = float(item.get("previousClose") or price)
        item.update({"value": price, "changePct": round(((price - previous) / previous * 100) if previous else 0.0, 4), "asOf": now_iso(), "live": True})
    fx_item = by_id.get("USD_KRW")
    if fx_item:
        fx = client.get_exchange_rate("KRW", "USD")
        rate = float(fx["midRate"])
        fx_item.update({"value": round(1 / rate) if rate else 0.0, "asOf": fx.get("validFrom") or now_iso(), "live": True})
    payload["generatedAt"] = now_iso()
    return payload


class LiveMarketState:
    def __init__(self, client: TossMarketClient) -> None:
        self.client = client
        self.payload: dict[str, Any] = {"instruments": []}
        self.macro: dict[str, Any] = {"items": []}
        self.clients: set[asyncio.Queue[dict[str, Any]]] = set()
        self.sequence = 0
        self.lock = asyncio.Lock()

    async def bootstrap(self) -> None:
        self.payload = await asyncio.to_thread(build_live_feed, self.client)
        self.macro = await asyncio.to_thread(build_macro_payload, self.client)
        self.payload["streaming"] = True
        self.payload["refreshHintSeconds"] = 1

    async def snapshot(self) -> dict[str, Any]:
        async with self.lock:
            snapshot = deepcopy(self.payload)
            snapshot["macro"] = deepcopy(self.macro)
            return snapshot

    async def update_macro(self) -> None:
        updated = await asyncio.to_thread(refresh_macro_payload, self.client, self.macro)
        async with self.lock:
            self.macro = updated
            self.sequence += 1
            event = {"type": "macro", "sequence": self.sequence, "payload": deepcopy(updated)}
            for queue in tuple(self.clients):
                if not queue.full():
                    queue.put_nowait(event)

    async def update_trade(self, frame: dict[str, Any]) -> None:
        topic = str(frame.get("topic", ""))
        data = frame.get("data")
        if not topic.startswith("trade:kr:") or not isinstance(data, dict):
            return
        symbol = topic.rsplit(":", 1)[-1]
        try:
            price = float(data["price"])
            timestamp = str(data["timestamp"])
        except (KeyError, TypeError, ValueError):
            return
        async with self.lock:
            instrument = next((item for item in self.payload.get("instruments", []) if item.get("symbol") == symbol), None)
            if instrument is None:
                return
            previous_close = float(instrument.get("previousClose") or price)
            change = price - previous_close
            change_pct = round((change / previous_close * 100) if previous_close else 0.0, 4)
            instrument.update({"price": price, "change": change, "changePct": change_pct, "asOf": timestamp})
            chart = instrument.get("chart")
            if isinstance(chart, list):
                point = {"timestamp": timestamp, "price": price}
                if chart and str(chart[-1].get("timestamp", ""))[:16] == timestamp[:16]:
                    chart[-1] = point
                else:
                    chart.append(point)
                    del chart[:-120]
            self.payload["generatedAt"] = now_iso()
            self.sequence += 1
            event = {
                "type": "trade",
                "sequence": self.sequence,
                "symbol": symbol,
                "price": price,
                "change": change,
                "changePct": change_pct,
                "asOf": timestamp,
            }
            for queue in tuple(self.clients):
                if queue.full():
                    continue
                queue.put_nowait(event)

    async def register(self) -> asyncio.Queue[dict[str, Any]] | None:
        async with self.lock:
            if len(self.clients) >= MAX_CLIENTS:
                return None
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=32)
            self.clients.add(queue)
            return queue

    async def unregister(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self.lock:
            self.clients.discard(queue)


async def run_toss_stream(state: LiveMarketState) -> None:
    """Keep one authenticated market-data stream and reconnect with backoff."""
    symbols = [symbol for symbol, _ in LIVE_INSTRUMENTS]
    delay = 1.0
    while True:
        try:
            token = await asyncio.to_thread(state.client.get_access_token)
            async with websockets.connect(
                WS_URL,
                additional_headers={"Authorization": f"Bearer {token}"},
                ping_interval=None,
                open_timeout=15,
                close_timeout=5,
                max_queue=128,
            ) as ws:
                await ws.send(json.dumps([{"id": "daily-briefing-live"}, {"type": "trade:kr", "codes": symbols}]))
                keepalive = asyncio.create_task(send_keepalive(ws))
                delay = 1.0
                try:
                    async for raw in ws:
                        if raw == "PING":
                            continue
                        try:
                            frame = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if frame.get("type") == "message":
                            await state.update_trade(frame)
                finally:
                    keepalive.cancel()
                    await asyncio.gather(keepalive, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Do not log headers, tokens, or upstream body contents.
            await asyncio.sleep(delay + random.uniform(0, 0.35))
            delay = min(delay * 2, 30)


async def run_macro_refresh(state: LiveMarketState) -> None:
    """Keep KOSPI/KOSDAQ and KRW/USD cards fresh without per-browser API polling."""
    while True:
        await asyncio.sleep(5)
        try:
            await state.update_macro()
        except asyncio.CancelledError:
            raise
        except Exception:
            # The last confirmed macro snapshot remains visible on provider failure.
            continue


async def send_keepalive(ws: Any) -> None:
    while True:
        await asyncio.sleep(60)
        await ws.send("PING")


def response_headers(status: str, content_type: str, origin: str | None) -> bytes:
    allowed = origin if origin == ALLOWED_ORIGIN else ALLOWED_ORIGIN
    return (
        f"HTTP/1.1 {status}\r\n"
        f"Content-Type: {content_type}\r\n"
        "Cache-Control: no-store, no-cache, must-revalidate\r\n"
        "Connection: keep-alive\r\n"
        f"Access-Control-Allow-Origin: {allowed}\r\n"
        "Vary: Origin\r\n\r\n"
    ).encode()


def websocket_frame(data: bytes) -> bytes:
    """Encode a server-to-browser text frame; browser frames are never trusted."""
    size = len(data)
    if size < 126:
        return bytes((0x81, size)) + data
    if size < 65536:
        return bytes((0x81, 126)) + size.to_bytes(2, "big") + data
    return bytes((0x81, 127)) + size.to_bytes(8, "big") + data


async def handle_websocket(state: LiveMarketState, writer: asyncio.StreamWriter, origin: str | None, headers: dict[str, str]) -> None:
    queue: asyncio.Queue[dict[str, Any]] | None = None
    try:
        key = headers.get("sec-websocket-key")
        if origin != ALLOWED_ORIGIN or not key:
            writer.write(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
            await writer.drain()
            return
        import base64
        import hashlib
        accept = base64.b64encode(hashlib.sha1(f"{key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11".encode()).digest()).decode()
        writer.write((
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
        ).encode())
        await writer.drain()
        queue = await state.register()
        if queue is None:
            return
        initial = {"type": "snapshot", "payload": await state.snapshot()}
        writer.write(websocket_frame(json.dumps(initial, ensure_ascii=False, separators=(",", ":")).encode()))
        await writer.drain()
        while True:
            event = await queue.get()
            writer.write(websocket_frame(json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode()))
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        if queue is not None:
            await state.unregister(queue)
        writer.close()
        await writer.wait_closed()


async def handle_http(state: LiveMarketState, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    queue: asyncio.Queue[dict[str, Any]] | None = None
    try:
        request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
        if len(request) > 8192:
            raise ValueError("headers too large")
        lines = request.decode("iso-8859-1").split("\r\n")
        method, path, _ = lines[0].split(" ", 2)
        headers = {key.strip().lower(): value.strip() for line in lines[1:] if ":" in line for key, value in [line.split(":", 1)]}
        origin = headers.get("origin")
        if path == "/api/v1/live-ws" and headers.get("upgrade", "").lower() == "websocket":
            await handle_websocket(state, writer, origin, headers)
            return
        if method == "OPTIONS":
            writer.write(response_headers("204 No Content", "text/plain", origin))
            await writer.drain()
            return
        if method != "GET":
            writer.write(response_headers("405 Method Not Allowed", "application/json", origin) + b'{"error":"method_not_allowed"}')
            await writer.drain()
            return
        if path == "/healthz":
            writer.write(response_headers("200 OK", "application/json", origin) + b'{"status":"ok"}')
            await writer.drain()
            return
        if path != "/api/v1/live-stream" or (origin is not None and origin != ALLOWED_ORIGIN):
            writer.write(response_headers("404 Not Found", "application/json", origin) + b'{"error":"not_found"}')
            await writer.drain()
            return
        queue = await state.register()
        if queue is None:
            writer.write(response_headers("503 Service Unavailable", "application/json", origin) + b'{"error":"capacity"}')
            await writer.drain()
            return
        writer.write(response_headers("200 OK", "text/event-stream; charset=utf-8", origin))
        initial = {"type": "snapshot", "payload": await state.snapshot()}
        writer.write(f"data: {json.dumps(initial, ensure_ascii=False, separators=(',', ':'))}\n\n".encode())
        await writer.drain()
        while True:
            event = await queue.get()
            writer.write(f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n".encode())
            await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionError, ValueError, UnicodeDecodeError, asyncio.TimeoutError):
        pass
    finally:
        if queue is not None:
            await state.unregister(queue)
        writer.close()
        await writer.wait_closed()


async def main(port: int, config_path: Path) -> None:
    client = TossMarketClient(TossMarketConfig.from_toml(config_path))
    state = LiveMarketState(client)
    await state.bootstrap()
    server = await asyncio.start_server(lambda reader, writer: handle_http(state, reader, writer), "127.0.0.1", port, limit=8192)
    stream = asyncio.create_task(run_toss_stream(state))
    macro_refresh = asyncio.create_task(run_macro_refresh(state))
    try:
        async with server:
            await server.serve_forever()
    finally:
        stream.cancel()
        macro_refresh.cancel()
        await asyncio.gather(stream, macro_refresh, return_exceptions=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read-only Toss tick relay for daily briefing")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--config", type=Path, default=Path("config/toss_market.toml"))
    args = parser.parse_args()
    asyncio.run(main(args.port, args.config))
