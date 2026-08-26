#!/usr/bin/env bash
# Publish only the public, secret-free live market feed for the static Pages site.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
LOCK="$ROOT/logs/live_market_feed.lock"

if [[ ! -x "$PYTHON" ]]; then
  PYTHON="python3"
fi

exec 9>"$LOCK"
flock -n 9 || exit 0

cd "$ROOT"
"$PYTHON" scripts/refresh_live_market_feed.py >/dev/null

git add public/market-live.json
if ! git diff --cached --quiet; then
  git commit -m "Refresh live market feed" >/dev/null
  git push >/dev/null
fi
