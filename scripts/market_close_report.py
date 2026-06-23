#!/usr/bin/env python3
"""Build a short Discord message for the 16:00 market-close briefing.

The detailed market-close research belongs in the generated HTML report via
logs/cycle_analysis.json. Discord should stay compact: 핵심요약 + 가격정보 + link.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_FILE = ROOT / "logs" / "latest_summary.json"
MENTION_USER_ID = "750311358855381087"


def money_krw(value: int) -> str:
    return f"{value:,}원"


def signed_money(value: int) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,}원"


def signed_pct(value: float) -> str:
    return f"{value:+.2f}%"


def metric_text(value, suffix="") -> str:
    if value is None:
        return "조회 제한"
    return f"{value:.2f}{suffix}"


def metric_text_signed(value, suffix="") -> str:
    if value is None:
        return "조회 제한"
    return f"{value:+.2f}{suffix}"


def load_summary() -> dict:
    if not SUMMARY_FILE.exists():
        raise RuntimeError(f"Summary file not found: {SUMMARY_FILE}")
    return json.loads(SUMMARY_FILE.read_text(encoding="utf-8"))


def build_message(summary: dict) -> str:
    prices = summary["prices"]
    macro = summary.get("macro", {})
    date = summary["date"]
    site_url = summary["site_url"]
    up_count = sum(1 for row in prices if row["change_pct"] >= 0)
    down_count = len(prices) - up_count

    fx = macro.get("원/달러", {})
    tnx = macro.get("미국 10년물", {})
    oil = macro.get("WTI", {})

    price_lines = "\n".join(
        f"- {row['name']}: {money_krw(row['close'])} ({signed_money(row['change'])}, {signed_pct(row['change_pct'])})"
        for row in prices
    )

    return (
        f"<@{MENTION_USER_ID}> {date} 마감 브리핑\n\n"
        f"핵심 요약\n"
        f"- {summary['cycle_summary']}\n"
        f"- 포트폴리오 기준 상승 {up_count}개 / 하락 {down_count}개입니다.\n"
        f"- 매크로: 원/달러 {metric_text(fx.get('value'), '원')} ({metric_text_signed(fx.get('change_pct'), '%')}), "
        f"미국 10년물 {metric_text(tnx.get('value'), '%')}, WTI {metric_text(oil.get('value'), '달러')} ({metric_text_signed(oil.get('change_pct'), '%')}).\n\n"
        f"가격정보\n"
        f"{price_lines}\n\n"
        f"자세한 내용은 보고서에서 확인하세요.\n"
        f"{site_url}"
    )


def main() -> None:
    print(build_message(load_summary()))


if __name__ == "__main__":
    main()
