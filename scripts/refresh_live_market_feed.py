#!/usr/bin/env python3
"""Generate the public live market feed without regenerating editorial content."""
from __future__ import annotations

from pathlib import Path
import sys

from market_data.config import TossConfigError
from market_data.live_feed import write_live_feed
from market_data.toss_client import TossMarketError

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    try:
        payload = write_live_feed(
            ROOT / "public" / "market-live.json",
            ROOT / "config" / "toss_market.toml",
        )
        print(f"live feed updated: {payload['generatedAt']} / {len(payload['instruments'])} instruments")
        return 0
    except (TossConfigError, TossMarketError, OSError, ValueError) as exc:
        print(f"live feed update failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
