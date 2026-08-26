from decimal import Decimal
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from market_data.config import TossConfigError, TossMarketConfig
from market_data.live_feed import LIVE_INSTRUMENTS, build_live_feed
from market_data.toss_client import Candle, Quote, TossMarketClient, TossMarketError


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, post_responses, get_responses):
        self.post_responses = list(post_responses)
        self.get_responses = list(get_responses)
        self.post_calls = []
        self.get_calls = []

    def post(self, *args, **kwargs):
        self.post_calls.append((args, kwargs))
        return self.post_responses.pop(0)

    def get(self, *args, **kwargs):
        self.get_calls.append((args, kwargs))
        return self.get_responses.pop(0)


def config():
    return TossMarketConfig(client_id="test_client_id", client_secret="test_client_secret")


def test_config_rejects_placeholder_secret(tmp_path):
    path = tmp_path / "toss_market.toml"
    path.write_text(
        '[toss_market]\nclient_id = "PASTE_CLIENT_ID_HERE"\nclient_secret = "PASTE_CLIENT_SECRET_HERE"\n',
        encoding="utf-8",
    )
    with pytest.raises(TossConfigError, match="client_id"):
        TossMarketConfig.from_toml(path)


def test_quotes_use_oauth_and_public_price_endpoint_only():
    session = FakeSession(
        [FakeResponse(200, {"access_token": "token-value", "token_type": "Bearer", "expires_in": 3600})],
        [
            FakeResponse(
                200,
                {"result": [{"symbol": "005930", "lastPrice": "72000", "currency": "KRW", "timestamp": "2026-08-26T09:30:00+09:00"}]},
            )
        ],
    )
    quotes = TossMarketClient(config(), session).get_quotes(["005930"])

    assert quotes[0].last_price == Decimal("72000")
    assert session.post_calls[0][0][0].endswith("/oauth2/token")
    assert session.get_calls[0][0][0].endswith("/api/v1/prices")
    assert session.get_calls[0][1]["params"] == {"symbols": "005930"}
    assert "orders" not in session.get_calls[0][0][0]
    assert "accounts" not in session.get_calls[0][0][0]


def test_unauthorized_request_refreshes_token_once():
    session = FakeSession(
        [
            FakeResponse(200, {"access_token": "first", "token_type": "Bearer", "expires_in": 3600}),
            FakeResponse(200, {"access_token": "second", "token_type": "Bearer", "expires_in": 3600}),
        ],
        [
            FakeResponse(401, {"error": {"code": "UNAUTHORIZED"}}),
            FakeResponse(200, {"result": [{"symbol": "005930", "lastPrice": "72000", "currency": "KRW"}]}),
        ],
    )
    quotes = TossMarketClient(config(), session).get_quotes(["005930"])

    assert quotes[0].symbol == "005930"
    assert len(session.post_calls) == 2
    assert len(session.get_calls) == 2
    assert session.get_calls[1][1]["headers"]["Authorization"] == "Bearer second"


def test_market_error_masks_credentials_on_http_failure():
    session = FakeSession(
        [FakeResponse(200, {"access_token": "secret-token", "token_type": "Bearer", "expires_in": 3600})],
        [FakeResponse(429, {"error": {"code": "RATE_LIMIT"}})],
    )
    with pytest.raises(TossMarketError) as exc_info:
        TossMarketClient(config(), session).get_quotes(["005930"])

    message = str(exc_info.value)
    assert "HTTP 429" in message
    assert "secret-token" not in message
    assert "test_client_id" not in message
    assert "test_client_secret" not in message


def test_client_has_no_account_or_order_methods():
    forbidden = {"get_account", "get_balance", "get_holdings", "place_order", "cancel_order"}
    assert not (forbidden & set(dir(TossMarketClient)))


class FakeLiveClient:
    def get_quotes(self, symbols):
        return [Quote(symbol=symbol, last_price=Decimal("110"), currency="KRW", timestamp="2026-08-26T09:01:00+09:00") for symbol in symbols]

    def get_candles(self, symbol, interval, count):
        base = Decimal("100") if interval == "1d" else Decimal("105")
        return [
            Candle(
                timestamp=f"2026-08-26T09:{index:02d}:00+09:00",
                open_price=base + index,
                high_price=base + index,
                low_price=base + index,
                close_price=base + index,
                volume=Decimal("1000"),
                currency="KRW",
            )
            for index in range(count, 0, -1)
        ]


def test_live_feed_is_public_json_with_intraday_chart_data():
    payload = build_live_feed(FakeLiveClient())

    assert payload["source"] == "Toss Securities Open API"
    assert len(payload["instruments"]) == len(LIVE_INSTRUMENTS)
    first = payload["instruments"][0]
    assert first["symbol"] == "005930"
    assert first["change"] == 6.0
    assert first["changePct"] == 5.7692
    assert first["chartInterval"] == "1m"
    assert len(first["chart"]) == 120
    assert "client_secret" not in str(payload).lower()
