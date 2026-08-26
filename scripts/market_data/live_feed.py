"""Public, secret-free JSON feed for the briefing page's live market widgets."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from zoneinfo import ZoneInfo

from .config import TossMarketConfig
from .toss_client import Candle, TossMarketClient

KST = ZoneInfo("Asia/Seoul")
LIVE_INSTRUMENTS = (
    ("005930", "삼성전자"),
    ("000660", "SK하이닉스"),
    ("396500", "TIGER 반도체TOP10"),
)


def _point(candle: Candle) -> dict[str, object]:
    return {"timestamp": candle.timestamp, "price": float(candle.close_price)}


def build_live_feed(client: TossMarketClient, *, now: datetime | None = None) -> dict[str, object]:
    """Fetch only public prices/candles and return browser-safe JSON data."""
    generated_at = (now or datetime.now(KST)).astimezone(KST)
    symbols = [symbol for symbol, _ in LIVE_INSTRUMENTS]
    quotes = {quote.symbol: quote for quote in client.get_quotes(symbols)}
    instruments = []
    for symbol, name in LIVE_INSTRUMENTS:
        quote = quotes.get(symbol)
        if quote is None:
            continue
        daily_desc = client.get_candles(symbol, interval="1d", count=5)
        intraday_desc = client.get_candles(symbol, interval="1m", count=120)
        daily = list(reversed(daily_desc))
        intraday = list(reversed(intraday_desc))
        previous_close = daily[-2].close_price if len(daily) >= 2 else quote.last_price
        change = quote.last_price - previous_close
        change_pct = float((change / previous_close * 100) if previous_close else 0)
        chart_points = intraday if len(intraday) >= 2 else daily
        instruments.append(
            {
                "symbol": symbol,
                "name": name,
                "currency": quote.currency,
                "price": float(quote.last_price),
                "change": float(change),
                "changePct": round(change_pct, 4),
                "asOf": quote.timestamp,
                "chartInterval": "1m" if chart_points is intraday else "1d",
                "chart": [_point(candle) for candle in chart_points],
                "daily": [_point(candle) for candle in daily[-5:]],
            }
        )
    return {
        "schemaVersion": 1,
        "source": "Toss Securities Open API",
        "generatedAt": generated_at.isoformat(),
        "refreshHintSeconds": 20,
        "instruments": instruments,
    }


def write_live_feed(output: Path, config_path: Path) -> dict[str, object]:
    """Atomically write a public feed. Credentials never enter output or errors."""
    config = TossMarketConfig.from_toml(config_path)
    payload = build_live_feed(TossMarketClient(config))
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, delete=False) as temp:
        json.dump(payload, temp, ensure_ascii=False, separators=(",", ":"))
        temp.write("\n")
        temp_path = Path(temp.name)
    temp_path.replace(output)
    return payload
