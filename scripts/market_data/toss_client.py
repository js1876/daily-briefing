"""Official Toss Securities Open API client restricted to public market data.

Deliberately contains no account, asset, order, or conditional-order endpoints.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import requests

from .config import TossMarketConfig


class TossMarketError(RuntimeError):
    """A safe error suitable for logs; never contains credentials or tokens."""


@dataclass(frozen=True)
class Quote:
    symbol: str
    last_price: Decimal
    currency: str
    timestamp: str | None


@dataclass(frozen=True)
class Candle:
    timestamp: str
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal
    currency: str


@dataclass(frozen=True)
class MarketIndicator:
    symbol: str
    last_price: Decimal
    timestamp: str | None


class TossMarketClient:
    """Read-only client for Toss public market-data endpoints only."""

    def __init__(self, config: TossMarketConfig, session: requests.Session | None = None):
        self.config = config
        self.session = session or requests.Session()
        self._access_token: str | None = None

    def _issue_access_token(self) -> str:
        response = self.session.post(
            f"{self.config.base_url}/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=self.config.timeout_seconds,
        )
        if response.status_code != 200:
            raise TossMarketError(f"토스 OAuth 토큰 발급 실패 (HTTP {response.status_code})")
        try:
            token = str(response.json()["access_token"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TossMarketError("토스 OAuth 토큰 응답 형식이 예상과 다릅니다.") from exc
        if not token:
            raise TossMarketError("토스 OAuth 응답에 access_token이 없습니다.")
        self._access_token = token
        return token

    def _request(self, path: str, params: dict[str, Any] | None = None) -> Any:
        token = self._access_token or self._issue_access_token()
        response = self.session.get(
            f"{self.config.base_url}{path}",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=self.config.timeout_seconds,
        )
        if response.status_code == 401:
            token = self._issue_access_token()
            response = self.session.get(
                f"{self.config.base_url}{path}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                timeout=self.config.timeout_seconds,
            )
        if response.status_code != 200:
            raise TossMarketError(f"토스 시장조회 실패: {path} (HTTP {response.status_code})")
        try:
            payload = response.json()
            return payload["result"]
        except (KeyError, TypeError, ValueError) as exc:
            raise TossMarketError(f"토스 시장조회 응답 형식이 예상과 다릅니다: {path}") from exc

    @staticmethod
    def _decimal(value: object, field: str) -> Decimal:
        try:
            return Decimal(str(value))
        except Exception as exc:
            raise TossMarketError(f"토스 시장조회 숫자 형식 오류: {field}") from exc

    def get_access_token(self) -> str:
        """Return the cached OAuth token for a read-only market-data WebSocket handshake."""
        return self._access_token or self._issue_access_token()

    def get_quotes(self, symbols: list[str]) -> list[Quote]:
        clean = [symbol.strip() for symbol in symbols if symbol.strip()]
        if not clean:
            return []
        result = self._request("/api/v1/prices", {"symbols": ",".join(clean)})
        return [
            Quote(
                symbol=str(item["symbol"]),
                last_price=self._decimal(item["lastPrice"], "lastPrice"),
                currency=str(item["currency"]),
                timestamp=item.get("timestamp"),
            )
            for item in result
        ]

    def get_candles(self, symbol: str, interval: str = "1d", count: int = 5) -> list[Candle]:
        if interval not in {"1m", "1d"}:
            raise ValueError("interval은 1m 또는 1d여야 합니다.")
        if not 1 <= count <= 200:
            raise ValueError("count는 1~200 범위여야 합니다.")
        result = self._request(
            "/api/v1/candles",
            {"symbol": symbol, "interval": interval, "count": count, "adjusted": "true"},
        )
        return [
            Candle(
                timestamp=str(item["timestamp"]),
                open_price=self._decimal(item["openPrice"], "openPrice"),
                high_price=self._decimal(item["highPrice"], "highPrice"),
                low_price=self._decimal(item["lowPrice"], "lowPrice"),
                close_price=self._decimal(item["closePrice"], "closePrice"),
                volume=self._decimal(item["volume"], "volume"),
                currency=str(item["currency"]),
            )
            for item in result["candles"]
        ]

    def get_daily_candles(self, symbol: str, count: int = 5) -> list[Candle]:
        return self.get_candles(symbol, interval="1d", count=count)

    def get_market_indicators(self, symbols: list[str]) -> list[MarketIndicator]:
        clean = [symbol.strip() for symbol in symbols if symbol.strip()]
        if not clean:
            return []
        result = self._request("/api/v1/market-indicators/prices", {"symbols": ",".join(clean)})
        return [
            MarketIndicator(
                symbol=str(item["symbol"]),
                last_price=self._decimal(item["lastPrice"], "lastPrice"),
                timestamp=item.get("timestamp"),
            )
            for item in result
        ]

    def get_exchange_rate(self, base_currency: str = "KRW", quote_currency: str = "USD") -> dict[str, Any]:
        return self._request(
            "/api/v1/exchange-rate",
            {"baseCurrency": base_currency, "quoteCurrency": quote_currency},
        )

    def get_kr_market_calendar(self) -> dict[str, Any]:
        return self._request("/api/v1/market-calendar/KR")
