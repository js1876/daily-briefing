import base64
import html
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
import numpy as np
import requests
import yfinance as yf
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch
from pykrx import stock


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = ROOT / "public"
CHART_DIR = PUBLIC_DIR / "assets" / "charts"
PUBLIC_REPORT_ARCHIVE_DIR = PUBLIC_DIR / "archive" / "reports"
ARCHIVE_DIR = ROOT / "archive"
REPORT_ARCHIVE_DIR = ARCHIVE_DIR / "reports"
MARKDOWN_ARCHIVE_DIR = ARCHIVE_DIR / "markdown"
CONFIG_DIR = ROOT / "config"
LOG_DIR = ROOT / "logs"
KST = ZoneInfo("Asia/Seoul")
FONT_PATH = "C:/Windows/Fonts/malgun.ttf"
WEBHOOK_FILE = CONFIG_DIR / "discord_webhook_url.txt"

DOMESTIC_STOCKS = [
    ("396500", "TIGER 반도체TOP10", "TIGER 반도체TOP10 396500"),
    ("498400", "KODEX 200타겟위클리커버드콜", "KODEX 200타겟위클리커버드콜 498400"),
    ("005930", "삼성전자", "삼성전자 005930"),
    ("000660", "SK하이닉스", "SK하이닉스 000660"),
]

ANALYSIS_STOCKS = {
    "005930.KS": "삼성전자",
    "000660.KS": "SK하이닉스",
}

UP = "#d62728"
DOWN = "#1f77b4"
TEXT = "#202124"
MUTED = "#6b7280"
GRID = "#e5e7eb"


@dataclass
class PriceRow:
    ticker: str
    name: str
    close: int
    prev_close: int
    change: int
    change_pct: float
    basis_date: datetime
    closes: list[int]
    dates: list[str]


def setup_font() -> None:
    font_manager.fontManager.addfont(FONT_PATH)
    font_name = font_manager.FontProperties(fname=FONT_PATH).get_name()
    plt.rcParams["font.family"] = font_name
    plt.rcParams["axes.unicode_minus"] = False


def krx_date(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def fetch_price_row(ticker: str, name: str, today: datetime) -> PriceRow:
    start = krx_date(today - timedelta(days=35))
    end = krx_date(today)
    df = stock.get_market_ohlcv_by_date(start, end, ticker)
    if df.empty or len(df) < 2:
        yf_df = yf.Ticker(f"{ticker}.KS").history(period="1mo", interval="1d", auto_adjust=False)
        if yf_df.empty or len(yf_df) < 2:
            raise RuntimeError(f"가격 데이터를 조회하지 못했습니다: {name} ({ticker})")
        closes = [int(v) for v in yf_df["Close"].dropna().tail(4).tolist()]
        dates = [f"{idx.month}/{idx.day}" if hasattr(idx, "month") else str(idx) for idx in yf_df.tail(4).index]
        basis_date = yf_df.index[-1].to_pydatetime().astimezone(KST)
        close = int(yf_df["Close"].iloc[-1])
        prev_close = int(yf_df["Close"].iloc[-2])
    else:
        df = df.dropna()
        closes = [int(v) for v in df["종가"].tail(4).tolist()]
        dates = [f"{idx.month}/{idx.day}" for idx in df.tail(4).index]
        basis_date = df.index[-1].to_pydatetime().replace(tzinfo=KST)
        close = int(df["종가"].iloc[-1])
        prev_close = int(df["종가"].iloc[-2])

    change = close - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0.0
    return PriceRow(ticker, name, close, prev_close, change, change_pct, basis_date, closes, dates)


def google_news_rss(query: str) -> str:
    params = urllib.parse.urlencode(
        {
            "q": f"{query} when:1d",
            "hl": "ko",
            "gl": "KR",
            "ceid": "KR:ko",
        }
    )
    return f"https://news.google.com/rss/search?{params}"


def fetch_news(query: str, today: datetime, limit: int = 3) -> list[dict]:
    url = google_news_rss(query)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        raw = urllib.request.urlopen(req, timeout=20).read()
    except Exception:
        return []

    root = ET.fromstring(raw)
    out = []
    for item in root.findall("./channel/item"):
        pub_date = item.findtext("pubDate") or ""
        try:
            published = parsedate_to_datetime(pub_date).astimezone(KST)
        except Exception:
            continue
        if published.date() != today.date():
            continue

        source_el = item.find("source")
        out.append(
            {
                "time": published.strftime("%H:%M"),
                "source": html.unescape((source_el.text or "").strip()) if source_el is not None else "",
                "title": html.unescape((item.findtext("title") or "").strip()),
                "link": (item.findtext("link") or "").strip(),
            }
        )
        if len(out) >= limit:
            break
    return out


def fetch_macro() -> dict:
    symbols = {
        "KRW=X": "원/달러",
        "^TNX": "미국 10년물",
        "CL=F": "WTI",
        "^KS11": "KOSPI",
    }
    macro = {}
    for symbol, label in symbols.items():
        try:
            hist = yf.Ticker(symbol).history(period="1mo", interval="1d", auto_adjust=False).dropna()
            last = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) > 1 else last
            macro[label] = {
                "value": float(last["Close"]),
                "change_pct": float((last["Close"] - prev["Close"]) / prev["Close"] * 100) if prev["Close"] else 0.0,
            }
        except Exception:
            macro[label] = {"value": None, "change_pct": None}
    return macro


def fetch_valuation() -> dict:
    values = {}
    for symbol, name in ANALYSIS_STOCKS.items():
        try:
            info = yf.Ticker(symbol).get_info()
            values[name] = {
                "market_cap": info.get("marketCap"),
                "forward_pe": info.get("forwardPE"),
                "price_to_book": info.get("priceToBook"),
            }
        except Exception:
            values[name] = {"market_cap": None, "forward_pe": None, "price_to_book": None}
    return values


def money_krw(value: int) -> str:
    return f"{value:,}원"


def signed_money(value: int) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,}원"


def signed_pct(value: float) -> str:
    return f"{value:+.2f}%"


def cap_text(value) -> str:
    if not value:
        return "조회 제한"
    return f"약 {value / 1_0000_0000_0000:.0f}조원"


def metric_text(value, suffix="") -> str:
    if value is None:
        return "조회 제한"
    return f"{value:.2f}{suffix}"


def metric_text_signed(value, suffix="") -> str:
    if value is None:
        return "조회 제한"
    return f"{value:+.2f}{suffix}"


def format_krw_short(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}백만원"
    return f"{value:,}원"


def save_change_chart(rows: list[PriceRow], out: Path) -> None:
    sorted_rows = sorted(rows, key=lambda row: row.change_pct)
    names = [row.name.replace("KODEX 200타겟위클리커버드콜", "KODEX 커버드콜") for row in sorted_rows]
    values = [row.change_pct for row in sorted_rows]
    colors = [UP if value >= 0 else DOWN for value in values]
    max_abs = max(max(abs(v) for v in values), 1.0)

    fig, ax = plt.subplots(figsize=(11.5, 5.8), dpi=170)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    ax.barh(names, values, color=colors, height=0.56)
    ax.axvline(0, color="#111827", linewidth=1.1)
    ax.grid(axis="x", color=GRID, linewidth=1, linestyle="-")
    ax.set_axisbelow(True)
    ax.set_title("전 거래일 대비 변동률", fontsize=19, fontweight="bold", color=TEXT, pad=18)
    ax.set_xlabel("변동률 (%)", fontsize=12, color=MUTED)
    ax.tick_params(axis="y", labelsize=12)
    ax.tick_params(axis="x", labelsize=11, colors=MUTED)
    ax.set_xlim(-max_abs * 1.25, max_abs * 1.45)
    label_x = max_abs * 1.15
    for idx, value in enumerate(values):
        ax.text(label_x, idx, signed_pct(value), va="center", ha="left", fontsize=13, fontweight="bold", color=colors[idx])
    for spine in ["top", "right", "left"]:
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    basis = rows[0].basis_date.strftime("%Y-%m-%d")
    ax.text(0.99, -0.13, f"기준: {basis} 종가 / 전 거래일 종가 대비", transform=ax.transAxes, ha="right", va="top", fontsize=10, color=MUTED)
    fig.tight_layout(rect=[0.02, 0.04, 1, 0.98])
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def save_price_trends(rows: list[PriceRow], out: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(12.5, 7.2), dpi=170)
    fig.patch.set_facecolor("white")
    axes = axes.ravel()

    ordered = sorted(rows, key=lambda row: ["삼성전자", "KODEX 200타겟위클리커버드콜", "SK하이닉스", "TIGER 반도체TOP10"].index(row.name))
    for ax, row in zip(axes, ordered):
        label = row.name.replace("KODEX 200타겟위클리커버드콜", "KODEX 커버드콜")
        color = UP if row.change_pct >= 0 else DOWN
        ax.plot(row.dates, row.closes, color=color, linewidth=2.8, marker="o", markersize=6)
        ax.fill_between(row.dates, row.closes, min(row.closes), color=color, alpha=0.08)
        ax.set_title(f"{label} ({row.ticker})", fontsize=14, fontweight="bold", color=TEXT, pad=10)
        ax.text(
            0.02,
            0.88,
            f"최근 종가 {format_krw_short(row.close)}  |  {signed_pct(row.change_pct)}",
            transform=ax.transAxes,
            fontsize=10.5,
            color=TEXT,
            bbox={"facecolor": "white", "edgecolor": GRID, "boxstyle": "round,pad=0.35"},
        )
        ax.grid(axis="y", color=GRID, linewidth=1)
        ax.tick_params(axis="x", labelsize=10, colors=MUTED)
        ax.tick_params(axis="y", labelsize=10, colors=MUTED)
        ax.yaxis.set_major_formatter(lambda x, _: f"{int(x):,}")
        for spine in ["top", "right"]:
            ax.spines[spine].set_visible(False)
        ax.spines["left"].set_color(GRID)
        ax.spines["bottom"].set_color(GRID)

    start = rows[0].basis_date.strftime("%Y-%m-%d")
    fig.suptitle("종목별 최근 4거래일 종가 흐름", fontsize=19, fontweight="bold", color=TEXT, y=0.99)
    fig.text(0.99, 0.01, f"기준일: {start}", ha="right", fontsize=10, color=MUTED)
    fig.tight_layout(rect=[0, 0.03, 1, 0.95])
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def save_cycle_chart(out: Path) -> None:
    fig, ax = plt.subplots(figsize=(15, 8.2), dpi=170)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    text = "#111827"
    muted = "#667085"
    grid = "#e5e7eb"
    green = "#0f766e"
    amber = "#f59e0b"
    red = "#d62728"
    blue = "#1f77b4"
    purple = "#7c3aed"

    x = np.linspace(0, 2 * np.pi, 600)
    y = np.sin(x)
    ax.axhspan(0.55, 1.18, color="#fef2f2", alpha=0.9, zorder=0)
    ax.axhspan(-0.18, 0.55, color="#fffbeb", alpha=0.9, zorder=0)
    ax.axhspan(-1.18, -0.18, color="#eff6ff", alpha=0.9, zorder=0)
    ax.axhline(0, color="#98a2b3", linewidth=1.2)
    ax.plot(x, y, color="#1f2937", linewidth=3.0, zorder=2)
    ax.fill_between(x, y, 0, where=y >= 0, color=red, alpha=0.12, interpolate=True)
    ax.fill_between(x, y, 0, where=y < 0, color=blue, alpha=0.12, interpolate=True)

    current_x = 0.43 * np.pi
    current_y = np.sin(current_x)
    ax.scatter([current_x], [current_y], s=260, color=red, edgecolor="white", linewidth=3, zorder=7)
    ax.plot([current_x, current_x], [-1.12, current_y], color=red, linewidth=2.4, linestyle="--", zorder=4)
    ax.annotate(
        "현재 위치\n호황 중반~후반 진입\n(약 3.5~4.5단계)",
        xy=(current_x, current_y),
        xytext=(current_x + 0.95, 1.16),
        arrowprops={"arrowstyle": "->", "color": red, "lw": 2},
        fontsize=14,
        fontweight="bold",
        color=red,
        ha="left",
        va="center",
        bbox={"boxstyle": "round,pad=0.45", "facecolor": "white", "edgecolor": red, "linewidth": 1.6},
    )

    phases = [
        (0.10 * np.pi, "회복 초입", "감산·재고 감소", green, 0.28, 0.15),
        (0.28 * np.pi, "가격 상승", "DRAM/NAND/HBM ASP 상승", amber, 0.28, 0.15),
        (0.50 * np.pi, "실적 호황구간", "영업이익 폭증", red, 0.28, 0.15),
        (0.76 * np.pi, "CAPEX 증가", "공급 확대 준비", purple, -0.28, -0.42),
        (1.00 * np.pi, "피크아웃 경계", "주가 선반영·수급 둔화", red, 0.28, 0.15),
        (1.32 * np.pi, "가격 하락", "공급 과잉·재고 증가", blue, 0.28, 0.15),
        (1.50 * np.pi, "불황 저점", "적자·감산", blue, 0.28, 0.15),
        (1.78 * np.pi, "다음 회복 준비", "재고 소진·투자 축소", green, 0.28, 0.15),
    ]
    for px, title, subtitle, color, title_offset, subtitle_offset in phases:
        py = np.sin(px)
        ax.scatter([px], [py], s=95, color=color, edgecolor="white", linewidth=2.5, zorder=5)
        ax.text(px, py + title_offset, title, ha="center", va="bottom", fontsize=13, fontweight="bold", color=color)
        ax.text(px, py + subtitle_offset, subtitle, ha="center", va="bottom", fontsize=10.5, color="#475467")

    ax.text(np.pi / 2, 1.29, "호황", ha="center", va="center", fontsize=18, fontweight="bold", color=red)
    ax.text(3 * np.pi / 2, -1.29, "불황", ha="center", va="center", fontsize=18, fontweight="bold", color=blue)
    ax.text(0.03, 0.02, "저점", transform=ax.transAxes, ha="left", va="bottom", fontsize=12, color=muted)
    ax.text(0.97, 0.02, "다음 사이클", transform=ax.transAxes, ha="right", va="bottom", fontsize=12, color=muted)

    evidence = [
        ("가격", "DRAM/NAND/HBM 가격 상승 구간"),
        ("실적", "영업이익 변화율이 강한 회복·확장 국면"),
        ("밸류", "호황기 저PER 착시 가능성 점검"),
        ("수급", "고점권 차익실현·외국인 수급 확인"),
        ("CAPEX", "생산능력 확대는 미래 공급 리스크"),
    ]
    panel_x = 4.15
    panel_y = 0.78
    ax.text(panel_x, panel_y, "판단 근거", fontsize=17, fontweight="bold", color=text, ha="left")
    for idx, (label, desc) in enumerate(evidence):
        yy = panel_y - 0.16 - idx * 0.14
        ax.text(panel_x, yy, label, fontsize=10.5, fontweight="bold", color="white", ha="center", va="center", bbox={"boxstyle": "round,pad=0.35", "facecolor": "#111827", "edgecolor": "#111827"})
        ax.text(panel_x + 0.28, yy, desc, fontsize=10.8, color=text, ha="left", va="center")

    ax.text(
        np.pi,
        -1.52,
        "투자 해석: 추세 추종은 가능하지만, 신규 진입은 눌림·외국인 매도 완화·금리/환율 안정 확인 후 분할 접근",
        ha="center",
        va="center",
        fontsize=13,
        color="#344054",
        bbox={"boxstyle": "round,pad=0.5", "facecolor": "#f9fafb", "edgecolor": grid},
    )
    ax.set_title("반도체 메모리 사이클 위치 추정", fontsize=27, fontweight="bold", color=text, pad=24)
    ax.set_xlim(-0.12, 2 * np.pi + 0.12)
    ax.set_ylim(-1.65, 1.55)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def css_from_existing() -> str:
    candidates = [
        PUBLIC_DIR / "latest.html",
        REPORT_ARCHIVE_DIR / "daily_briefing_2026-06-03.html",
    ]
    existing = next((path for path in candidates if path.exists()), None)
    if existing is None:
        return ""
    text = existing.read_text(encoding="utf-8")
    start = text.index("<style>") + len("<style>")
    end = text.index("</style>")
    return text[start:end]


def news_article_html(name: str, items: list[dict]) -> str:
    if not items:
        return f"""
        <article class="stock-news">
          <h3>{html.escape(name)}</h3>
          <p class="empty">오늘자 뉴스 0건</p>
        </article>"""
    lis = []
    for item in items:
        lis.append(
            f"""
            <li>
              <span class="source">{html.escape(item['time'])} | {html.escape(item['source'])}</span>
              <a href="{html.escape(item['link'])}">{html.escape(item['title'])}</a>
            </li>"""
        )
    return f"""
        <article class="stock-news">
          <h3>{html.escape(name)}</h3>
          <ol>{''.join(lis)}
          </ol>
        </article>"""


def render_html(rows: list[PriceRow], news: dict, macro: dict, valuation: dict, today: datetime, chart_files: dict) -> str:
    css = css_from_existing()
    basis_date = rows[0].basis_date.strftime("%Y-%m-%d")
    today_s = today.strftime("%Y-%m-%d")
    up_count = sum(1 for row in rows if row.change_pct >= 0)
    down_count = len(rows) - up_count
    max_row = max(rows, key=lambda row: abs(row.change_pct))
    max_up = max(rows, key=lambda row: row.change_pct)
    max_down = min(rows, key=lambda row: row.change_pct)

    summary_line = (
        "메모리 사이클은 호황 중반~후반 구간에 있고, 가격·실적 모멘텀은 유효하지만 수급·금리·환율 리스크 확인이 필요합니다."
    )
    table_rows = "\n".join(
        f"""
            <tr>
              <td>{html.escape(row.name)}</td>
              <td>{row.ticker}</td>
              <td>{money_krw(row.close)}</td>
              <td>{money_krw(row.prev_close)}</td>
              <td class="{'up' if row.change >= 0 else 'down'}">{signed_money(row.change)}</td>
              <td class="{'up' if row.change_pct >= 0 else 'down'}">{signed_pct(row.change_pct)}</td>
            </tr>"""
        for row in rows
    )
    text_bars = "\n".join(
        f"""
        <div class="bar-row">
          <strong>{html.escape(row.name.replace("KODEX 200타겟위클리커버드콜", "KODEX 커버드콜"))}</strong>
          <span class="{'up' if row.change_pct >= 0 else 'down'}">{'▲' if row.change_pct >= 0 else '▼'} {signed_pct(row.change_pct)}</span>
          <div class="bar-track"><div class="bar-fill {'up-bg' if row.change_pct >= 0 else 'down-bg'}" style="width: {max(3, min(100, abs(row.change_pct) / max(abs(max_row.change_pct), 0.01) * 100)):.0f}%"></div></div>
        </div>"""
        for row in sorted(rows, key=lambda r: r.change_pct, reverse=True)
    )
    news_html = "\n".join(news_article_html(row.name, news.get(row.ticker, [])) for row in rows)

    samsung = valuation.get("삼성전자", {})
    hynix = valuation.get("SK하이닉스", {})
    fx = macro.get("원/달러", {})
    tnx = macro.get("미국 10년물", {})
    oil = macro.get("WTI", {})
    kospi = macro.get("KOSPI", {})

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>일일 포트폴리오 브리핑 - {today_s}</title>
  <style>{css}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>일일 포트폴리오 브리핑</h1>
      <p class="meta">작성일: {today_s} KST | 가격 기준: {basis_date} 종가</p>
    </header>

    <div class="summary">
      <div class="tile">
        <div class="tile-label">오늘의 핵심 한 줄</div>
        <div class="tile-value">반도체 사이클 호황 검증 구간</div>
        <p class="meta">{summary_line}</p>
      </div>
      <div class="tile">
        <div class="tile-label">상승 / 하락</div>
        <div class="tile-value"><span class="up">{up_count}</span> / <span class="down">{down_count}</span></div>
        <p class="meta">상승 {up_count}종목, 하락 {down_count}종목</p>
      </div>
      <div class="tile">
        <div class="tile-label">최대 변동</div>
        <div class="tile-value"><span class="{'up' if max_up.change_pct >= abs(max_down.change_pct) else 'down'}">{html.escape(max_row.name)} {signed_pct(max_row.change_pct)}</span></div>
        <p class="meta">최대 상승: {max_up.name} {signed_pct(max_up.change_pct)} | 최대 하락: {max_down.name} {signed_pct(max_down.change_pct)}</p>
      </div>
    </div>

    <section>
      <h2>가격 요약</h2>
      <p class="meta">당일 장중 데이터가 제한되는 경우 마지막 확인 가능 거래일 종가를 기준으로 정리합니다.</p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>종목</th><th>티커</th><th>기준 가격</th><th>전 거래일 종가</th><th>등락</th><th>변동률</th>
            </tr>
          </thead>
          <tbody>{table_rows}
          </tbody>
        </table>
      </div>
    </section>

    <section>
      <h2>시각화</h2>
      <div class="charts">
        <figure>
          <img src="{chart_files['change']}" alt="전 거래일 대비 변동률 차트">
          <figcaption>전 거래일 대비 변동률 차트입니다. 수치 라벨을 오른쪽 고정 영역으로 분리해 종목명과 겹치지 않게 했습니다.</figcaption>
        </figure>
        <figure>
          <img src="{chart_files['trend']}" alt="종목별 최근 4거래일 종가 흐름 차트">
          <figcaption>종목별 최근 4거래일 종가 흐름입니다. 단일 변동률보다 가격 흐름을 파악하기 쉽도록 4개 패널로 나눴습니다.</figcaption>
        </figure>
      </div>
    </section>

    <section>
      <h2>텍스트형 변동률 그래픽</h2>
      <div class="text-bars">{text_bars}
      </div>
    </section>

    <section>
      <h2>반도체 사이클 위치</h2>
      <figure>
        <img src="{chart_files['cycle']}" alt="반도체 메모리 사이클 위치 추정">
        <figcaption>사인파형으로 표현한 반도체 메모리 사이클입니다. 현재는 회복 초입이 아니라 호황 중반~후반, 즉 실적 호황과 CAPEX 증가 사이에 가까운 위치로 표시했습니다.</figcaption>
      </figure>
    </section>

    <section>
      <h2>반도체 섹터 투자 분석 리포트</h2>
      <p class="meta">분석 대상: 삼성전자, SK하이닉스, TIGER 반도체TOP10, KODEX 200타겟위클리커버드콜 | 데이터 기준: {basis_date} 종가 및 {today_s} 확인 자료</p>

      <h3>1. 요약</h3>
      <p><strong>현재 메모리 사이클은 공급 부족 - 가격 상승 - 실적 폭증 - 주가 상승 구간에 있으며, 동시에 CAPEX 확대와 밸류에이션 피크아웃 리스크가 같이 켜진 중후반부 진입 국면입니다.</strong></p>
      <p class="note">투자 결론은 “추세 추종은 유효하지만, 신규 진입은 가격 눌림·외국인 매도 완화·금리 안정 확인 후 분할 접근”입니다.</p>

      <h3>2. 반도체 사이클 진단</h3>
      <div class="table-wrap">
        <table>
          <thead><tr><th>지표</th><th>현재 관찰값</th><th>사이클 해석</th><th>투자 함의</th></tr></thead>
          <tbody>
            <tr><td>수요·공급</td><td>DRAM/NAND/HBM 가격 상승 및 AI 서버 수요 중심</td><td>공급 부족과 가격 상승 구간</td><td>메모리 업체 실적 모멘텀은 유효</td></tr>
            <tr><td>영업이익 방향</td><td>실적 변화율이 강한 회복·확장 국면</td><td>절대 이익보다 변화율이 중요한 구간</td><td>실적 상향은 주가 하방 지지, 피크아웃 감시 필요</td></tr>
            <tr><td>PER의 역설</td><td>삼성전자 forward PER {metric_text(samsung.get('forward_pe'), '배')}, SK하이닉스 {metric_text(hynix.get('forward_pe'), '배')}</td><td>호황기 저PER은 싸 보이는 착시일 수 있음</td><td>PER 단독 저평가 판단은 위험</td></tr>
            <tr><td>PBR 위치</td><td>삼성전자 PBR {metric_text(samsung.get('price_to_book'), '배')}, SK하이닉스 {metric_text(hynix.get('price_to_book'), '배')}</td><td>저점권보다 모멘텀 프리미엄 구간 여부 확인</td><td>PBR보다 이익·수급 검증이 중요</td></tr>
            <tr><td>CAPEX</td><td>HBM·AI 메모리 공급 확대 경쟁</td><td>공급 부족이 설비투자 증가 단계로 이동</td><td>단기 호재, 중장기 공급 과잉 리스크</td></tr>
          </tbody>
        </table>
      </div>

      <h3>3. 기업별 상대 비교 분석</h3>
      <div class="table-wrap">
        <table>
          <thead><tr><th>기업</th><th>현재 강점</th><th>약점·리스크</th><th>시장 평가</th><th>주가 탄력성 판단</th></tr></thead>
          <tbody>
            <tr><td>삼성전자</td><td>메모리·파운드리·패키징 턴키 포트폴리오와 HBM 추격 모멘텀</td><td>HBM 고객 승인·수율 확인 필요, 범용 제품 비중 존재</td><td>시가총액 {cap_text(samsung.get('market_cap'))}, forward PER {metric_text(samsung.get('forward_pe'), '배')}</td><td>후발 모멘텀. HBM 확인 시 탄력 가능</td></tr>
            <tr><td>SK하이닉스</td><td>HBM 선두 프리미엄, AI 메모리 순도 높음</td><td>선두주자 프리미엄과 CAPEX 부담, 단기 급등 피로</td><td>시가총액 {cap_text(hynix.get('market_cap'))}, forward PER {metric_text(hynix.get('forward_pe'), '배')}</td><td>선두주자. 추가 상승은 HBM 가격 지속성과 외국인 수급이 좌우</td></tr>
            <tr><td>TIGER 반도체TOP10</td><td>개별 종목 리스크를 줄인 반도체 바스켓 노출</td><td>대형 반도체주 쏠림 영향이 큼</td><td>{signed_pct(next(row.change_pct for row in rows if row.ticker == '396500'))}</td><td>섹터 베타 투자에 적합</td></tr>
            <tr><td>KODEX 200타겟위클리커버드콜</td><td>옵션 프리미엄·분배형 목적 가능</td><td>강한 추세장에서 초과수익 제한 가능</td><td>{signed_pct(next(row.change_pct for row in rows if row.ticker == '498400'))}</td><td>방어·현금흐름형 포지션</td></tr>
          </tbody>
        </table>
      </div>

      <h3>4. 매크로 및 리스크 팩터 분석</h3>
      <div class="table-wrap">
        <table>
          <thead><tr><th>요인</th><th>현재 데이터</th><th>반도체주 영향</th><th>해석</th></tr></thead>
          <tbody>
            <tr><td>FOMO·급등 피로</td><td>KOSPI {metric_text(kospi.get('value'))}, 전일 대비 {metric_text(kospi.get('change_pct'), '%')}</td><td>추격 매수 리스크 상승</td><td>사이클은 좋지만 주가 선반영 점검 필요</td></tr>
            <tr><td>환율</td><td>원/달러 {metric_text(fx.get('value'), '원')}, 전일 대비 {metric_text(fx.get('change_pct'), '%')}</td><td>수출주 이익에는 우호적이나 외국인 자금 이탈 우려</td><td>수급·금융시장 불안 변수</td></tr>
            <tr><td>미국 10년물 금리</td><td>{metric_text(tnx.get('value'), '%')}</td><td>성장주 밸류에이션 할인율 상승</td><td>AI 기대와 금리 부담이 공존</td></tr>
            <tr><td>유가·인플레이션</td><td>WTI {metric_text(oil.get('value'), '달러')}, 전일 대비 {metric_text(oil.get('change_pct'), '%')}</td><td>물가·금리 경계로 기술주 투자심리 압박</td><td>외부 충격 변수</td></tr>
            <tr><td>정책 리스크</td><td>AI 초과이익 과세·규제성 발언 확인 필요</td><td>AI 수혜주 프리미엄 할인 가능</td><td>실적 변수보다 심리 변수로 관리</td></tr>
          </tbody>
        </table>
      </div>

      <h3>5. 실전 투자 체크리스트</h3>
      <div class="table-wrap">
        <table>
          <thead><tr><th>구분</th><th>체크 질문</th><th>매수·보유 쪽 신호</th><th>비중 축소 쪽 신호</th></tr></thead>
          <tbody>
            <tr><td>저점 판단</td><td>실적 변화율이 개선되고 있는가?</td><td>영업이익 상향, 적자 축소, 가격 상승 지속</td><td>이익 추정치 하향 전환</td></tr>
            <tr><td>고점 판단</td><td>저PER이 이익 피크 착시인가?</td><td>가격 상승률이 아직 이익 추정 상향보다 빠르지 않음</td><td>PER은 낮지만 메모리 가격·주문 증가율 둔화</td></tr>
            <tr><td>수급</td><td>외국인 매도가 멈추는가?</td><td>외국인 순매수 전환 또는 매도 강도 완화</td><td>대형주 외국인 매도 지속</td></tr>
            <tr><td>HBM 순도</td><td>HBM 물량·가격·고객사가 확인되는가?</td><td>장기계약, 샘플 승인, 수율 개선</td><td>로드맵 발표만 있고 매출 반영 지연</td></tr>
            <tr><td>매크로</td><td>환율·금리·유가가 안정되는가?</td><td>10년물 금리 하락, 원화 안정, 유가 진정</td><td>금리 상승, 원/달러 급등, 유가 상승</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <section>
      <h2>종목별 뉴스</h2>
      <p class="meta">KST 기준 {today_s} 발행분만 포함했습니다. Google News RSS 검색은 when:1d 파라미터를 사용했습니다.</p>
      <div class="news-grid">{news_html}
      </div>
    </section>

    <section>
      <h2>오늘의 액션</h2>
      <ol class="actions">
        <li>신규 매수·매도 판단은 장 시작 후 가격 갭과 거래대금 확인 뒤 진행합니다.</li>
        <li>반도체 대형주는 사이클 모멘텀이 유효하지만, 추격 매수보다는 눌림·수급 완화 확인이 우선입니다.</li>
        <li>SK하이닉스와 TIGER 반도체TOP10은 HBM·반도체 업황 뉴스가 가격 반등으로 이어지는지 확인합니다.</li>
        <li>KODEX 200타겟위클리커버드콜은 분배·옵션 프리미엄 목적의 보유 전략 점검에 집중합니다.</li>
      </ol>
      <p class="note">이 파일은 자동 생성 결과입니다. 투자 판단 전 원문 뉴스와 실시간 호가를 다시 확인하세요.</p>
    </section>
  </main>
</body>
</html>
"""


def make_self_contained_html(source: Path, chart_files: dict, out: Path) -> None:
    text = source.read_text(encoding="utf-8")
    for filename in chart_files.values():
        path = PUBLIC_DIR / filename
        if not path.exists():
            continue
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        text = text.replace(f'src="{filename}"', f'src="data:image/png;base64,{encoded}"')
    out.write_text(text, encoding="utf-8")


def read_webhook_url() -> str | None:
    import os

    value = os.environ.get("DISCORD_WEBHOOK_URL", "").strip().lstrip("\ufeff")
    if value:
        return value
    if WEBHOOK_FILE.exists():
        value = WEBHOOK_FILE.read_text(encoding="utf-8-sig").strip().lstrip("\ufeff")
        if value and not value.startswith("#"):
            return value
    return None


def discord_message(rows: list[PriceRow], macro: dict, today: datetime) -> str:
    today_s = today.strftime("%Y-%m-%d")
    up_count = sum(1 for row in rows if row.change_pct >= 0)
    down_count = len(rows) - up_count
    max_up = max(rows, key=lambda row: row.change_pct)
    max_down = min(rows, key=lambda row: row.change_pct)

    fx = macro.get("원/달러", {})
    tnx = macro.get("미국 10년물", {})
    oil = macro.get("WTI", {})

    price_lines = "\n".join(
        f"- {row.name}: {money_krw(row.close)} ({signed_money(row.change)}, {signed_pct(row.change_pct)})"
        for row in rows
    )
    return (
        f"{today_s} 오늘의 브리핑 전달드립니다\n\n"
        f"핵심 요약\n"
        f"- 반도체 사이클은 호황 중반~후반 구간으로 판단하며, 추세는 유효하지만 신규 진입은 눌림과 수급 확인이 우선입니다.\n"
        f"- 상승 {up_count}개 / 하락 {down_count}개, 최대 상승은 {max_up.name} {signed_pct(max_up.change_pct)}, 최대 하락은 {max_down.name} {signed_pct(max_down.change_pct)}입니다.\n"
        f"- 매크로: 원/달러 {metric_text(fx.get('value'), '원')} ({metric_text_signed(fx.get('change_pct'), '%')}), 미국 10년물 {metric_text(tnx.get('value'), '%')}, WTI {metric_text(oil.get('value'), '달러')} ({metric_text_signed(oil.get('change_pct'), '%')}).\n\n"
        f"종목별 가격정보\n"
        f"{price_lines}\n\n"
        f"세부정보는 아래 첨부 HTML에서 확인하세요."
    )


def send_discord_webhook(webhook_url: str, rows: list[PriceRow], macro: dict, today: datetime, html_file: Path) -> None:
    payload = {"content": discord_message(rows, macro, today)}
    with html_file.open("rb") as f:
        files = {
            "payload_json": (None, __import__("json").dumps(payload, ensure_ascii=False), "application/json"),
            "files[0]": (html_file.name, f, "text/html"),
        }
        response = requests.post(webhook_url, files=files, timeout=30)
    response.raise_for_status()


def main() -> None:
    setup_font()
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_REPORT_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    MARKDOWN_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    today = datetime.now(KST)
    date_slug = today.strftime("%Y-%m-%d")

    rows = [fetch_price_row(ticker, name, today) for ticker, name, _ in DOMESTIC_STOCKS]
    news = {ticker: fetch_news(query, today) for ticker, _, query in DOMESTIC_STOCKS}
    macro = fetch_macro()
    valuation = fetch_valuation()

    chart_files = {
        "change": f"assets/charts/daily_briefing_change_chart_{date_slug}.png",
        "trend": f"assets/charts/daily_briefing_price_trends_{date_slug}.png",
        "cycle": f"assets/charts/daily_briefing_semiconductor_cycle_{date_slug}.png",
    }
    save_change_chart(rows, PUBLIC_DIR / chart_files["change"])
    save_price_trends(rows, PUBLIC_DIR / chart_files["trend"])
    save_cycle_chart(PUBLIC_DIR / chart_files["cycle"])

    rendered = render_html(rows, news, macro, valuation, today, chart_files)
    latest = PUBLIC_DIR / "latest.html"
    index = PUBLIC_DIR / "index.html"
    dated = REPORT_ARCHIVE_DIR / f"daily_briefing_{date_slug}.html"
    public_dated = PUBLIC_REPORT_ARCHIVE_DIR / f"daily_briefing_{date_slug}.html"
    bundle = PUBLIC_DIR / "latest_bundle.html"
    latest.write_text(rendered, encoding="utf-8")
    index.write_text(rendered, encoding="utf-8")
    make_self_contained_html(latest, chart_files, bundle)
    make_self_contained_html(latest, chart_files, dated)
    make_self_contained_html(latest, chart_files, public_dated)

    webhook_url = read_webhook_url()
    if webhook_url:
        send_discord_webhook(webhook_url, rows, macro, today, bundle)
        print("Discord webhook sent")
    else:
        print("Discord webhook skipped: set DISCORD_WEBHOOK_URL or discord_webhook_url.txt")

    print(latest)
    print(index)
    print(dated)
    print(public_dated)
    print(bundle)


if __name__ == "__main__":
    main()
