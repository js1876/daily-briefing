#!/usr/bin/env python3
"""Keep the static GitHub Pages WebSocket URL aligned with a Quick Tunnel restart.

Quick Tunnels have an ephemeral hostname. A named Cloudflare Tunnel is preferable,
but this watcher preserves the live-page endpoint until one is configured.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path('/home/js/Desktop/daily-briefing')
GENERATOR = ROOT / 'scripts/generate_daily_briefing.py'
URL_RE = re.compile(r'https://[a-z0-9-]+\.trycloudflare\.com')
ATTR_RE = re.compile(r'data-live-stream="https://[a-z0-9-]+\.trycloudflare\.com/api/v1/live-stream"')


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, check=check, text=True, capture_output=True)


def publish(url: str) -> None:
    source = GENERATOR.read_text()
    replacement = f'data-live-stream="{url}/api/v1/live-stream"'
    updated, count = ATTR_RE.subn(replacement, source, count=1)
    if count != 1 or updated == source:
        return
    if run('git', 'status', '--porcelain').stdout.strip():
        return
    GENERATOR.write_text(updated)
    try:
        run('/home/js/Desktop/daily-briefing/.venv/bin/python', 'scripts/generate_daily_briefing.py')
        run('git', 'add', 'scripts/generate_daily_briefing.py', 'public/latest.html', 'public/index.html')
        run('git', 'commit', '-m', 'Refresh live relay endpoint')
        run('git', 'push')
    except subprocess.CalledProcessError:
        run('git', 'restore', '--staged', '.', check=False)
        run('git', 'restore', 'scripts/generate_daily_briefing.py', 'public/latest.html', 'public/index.html', check=False)
    finally:
        for path in (ROOT / 'archive/reports/daily_briefing_2026-08-26.html', ROOT / 'public/archive/reports/daily_briefing_2026-08-26.html'):
            path.unlink(missing_ok=True)


def main() -> None:
    process = subprocess.Popen(
        ['journalctl', '--user', '-f', '-u', 'daily-briefing-live-tunnel.service', '-n', '0', '-o', 'cat'],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    assert process.stdout is not None
    for line in process.stdout:
        match = URL_RE.search(line)
        if match:
            publish(match.group(0))


if __name__ == '__main__':
    main()
