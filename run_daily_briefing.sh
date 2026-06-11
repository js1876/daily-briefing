#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="python3"
fi

mkdir -p logs
{
  echo "==== $(date -Is) generate daily briefing ===="
  "$PYTHON" scripts/generate_daily_briefing.py

  if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git add index.html public archive README.md .gitignore scripts run_daily_briefing.sh requirements.txt >/dev/null 2>&1 || true
    if ! git diff --cached --quiet; then
      git commit -m "Update daily briefing" >/dev/null 2>&1 || true
      git push >/dev/null 2>&1 || true
    fi
  fi
} >> logs/daily_briefing_task.log 2>&1

"$PYTHON" scripts/direct_channel_report.py
