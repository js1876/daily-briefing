import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "market_close_report.py"
spec = importlib.util.spec_from_file_location("market_close_report", MODULE_PATH)
assert spec is not None and spec.loader is not None
mcr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcr)


def test_market_close_message_is_short_and_excludes_weather_schedule():
    summary = {
        "date": "2026-06-23",
        "site_url": "https://js1876.github.io/daily-briefing/public/",
        "cycle_summary": "마감 기준 핵심 요약입니다.",
        "prices": [
            {"name": "삼성전자", "close": 1000, "change": -10, "change_pct": -1.0},
            {"name": "SK하이닉스", "close": 2000, "change": 20, "change_pct": 1.0},
        ],
        "macro": {
            "원/달러": {"value": 1400.0, "change_pct": 0.1},
            "미국 10년물": {"value": 4.5, "change_pct": 0.2},
            "WTI": {"value": 70.0, "change_pct": -1.0},
        },
    }

    message = mcr.build_message(summary)

    assert "마감 브리핑" in message
    assert "가격정보" in message
    assert "삼성전자" in message
    assert "오늘의 날씨" not in message
    assert "오늘의 일정" not in message
    assert "증시 동향" not in message
    assert "원인 분석" not in message
