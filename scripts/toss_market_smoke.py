#!/usr/bin/env python3
"""Read-only Toss Securities market-data smoke test.

This script intentionally calls only OAuth and public market-data endpoints.
It contains no account, asset, order, or conditional-order logic.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from market_data.config import TossConfigError, TossMarketConfig
from market_data.toss_client import TossMarketClient, TossMarketError

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "toss_market.toml"
DEFAULT_SYMBOLS = ["005930", "000660", "396500"]


def format_decimal(value) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def main() -> int:
    parser = argparse.ArgumentParser(description="토스증권 Open API 시장조회 전용 스모크 테스트")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS), help="쉼표로 구분한 종목 심볼")
    parser.add_argument("--candles", type=int, default=4, help="각 종목의 일봉 개수 (1~200)")
    args = parser.parse_args()

    try:
        config = TossMarketConfig.from_toml(args.config)
        client = TossMarketClient(config)
        symbols = [value.strip() for value in args.symbols.split(",") if value.strip()]
        quotes = client.get_quotes(symbols)
        calendar = client.get_kr_market_calendar()
        print("토스증권 Open API 시장조회 연결 성공")
        print(f"국내 장 상태: {calendar}")
        print("\n현재가")
        for quote in quotes:
            timestamp = quote.timestamp or "시각 미제공"
            print(f"- {quote.symbol}: {format_decimal(quote.last_price)} {quote.currency} ({timestamp})")

        print("\n최근 일봉")
        for symbol in symbols:
            candles = client.get_daily_candles(symbol, args.candles)
            if not candles:
                print(f"- {symbol}: 데이터 없음")
                continue
            latest = candles[0]
            print(
                f"- {symbol}: {latest.timestamp} 종가 {format_decimal(latest.close_price)} "
                f"/ 거래량 {format_decimal(latest.volume)} {latest.currency}"
            )
        return 0
    except (TossConfigError, TossMarketError, ValueError) as exc:
        print(f"토스 시장조회 준비/연결 실패: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
