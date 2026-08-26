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


def now_iso() -> str:
    return datetime.now(KST).isoformat()


class LiveMarketState:
    def __init__(self, client: TossMarketClient) -> None:
        self.client = client
        self.payload: dict[str, Any] = {"instruments": []}
        self.clients: set[asyncio.Queue[dict[str, Any]]] = set()
        self.sequence = 0
        self.lock = asyncio.Lock()

    async def bootstrap(self) -> None:
        self.payload = await asyncio.to_thread(build_live_feed, self.client)
        self.payload["streaming"] = True
        self.payload["refreshHintSeconds"] = 1

    async def snapshot(self) -> dict[str, Any]:
        async with self.lock:
            return deepcopy(self.payload)

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
    try:
        async with server:
            await server.serve_forever()
    finally:
        stream.cancel()
        await asyncio.gather(stream, return_exceptions=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read-only Toss tick relay for daily briefing")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--config", type=Path, default=Path("config/toss_market.toml"))
    args = parser.parse_args()
    asyncio.run(main(args.port, args.config))
