import base64
import html
import json
import os
import re
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
FONT_CANDIDATES = [
    os.environ.get("DAILY_BRIEFING_FONT", ""),
    "C:/Windows/Fonts/malgun.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Regular.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
WEBHOOK_FILE = CONFIG_DIR / "discord_webhook_url.txt"
CYCLE_ANALYSIS_FILE = LOG_DIR / "cycle_analysis.json"
DEFAULT_CYCLE_ANALYSIS = {
    "headline": "반도체 사이클 호황 검증 구간",
    "summary_line": "메모리 사이클은 호황 중반~후반 구간에 있고, 가격·실적 모멘텀은 유효하지만 수급·금리·환율 리스크 확인이 필요합니다.",
    "cycle_summary": "반도체 사이클은 호황 중반~후반 구간으로 판단하며, 추세는 유효하지만 신규 진입은 눌림과 수급 확인이 우선입니다.",
    "chart_caption": "사인파형으로 표현한 반도체 메모리 사이클입니다. 현재는 회복 초입이 아니라 호황 중반~후반, 즉 실적 호황과 CAPEX 증가 사이에 가까운 위치로 표시했습니다.",
    "report_html": """
      <h3>1. 요약</h3>
      <p><strong>현재 메모리 사이클은 공급 부족 - 가격 상승 - 실적 폭증 - 주가 상승 구간에 있으며, 동시에 CAPEX 확대와 밸류에이션 피크아웃 리스크가 같이 켜진 중후반부 진입 국면입니다.</strong></p>
      <p class=\"note\">투자 결론은 “추세 추종은 유효하지만, 신규 진입은 가격 눌림·외국인 매도 완화·금리 안정 확인 후 분할 접근”입니다.</p>
    """.strip(),
    "action_items": [
        "신규 매수·매도 판단은 장 시작 후 가격 갭과 거래대금 확인 뒤 진행합니다.",
        "반도체 대형주는 사이클 모멘텀이 유효하지만, 추격 매수보다는 눌림·수급 완화 확인이 우선입니다.",
        "SK하이닉스와 TIGER 반도체TOP10은 HBM·반도체 업황 뉴스가 가격 반등으로 이어지는지 확인합니다.",
        "KODEX 200타겟위클리커버드콜은 분배·옵션 프리미엄 목적의 보유 전략 점검에 집중합니다.",
    ],
}

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
    """Configure a Korean-capable font when available, with a portable fallback."""
    for font_path in FONT_CANDIDATES:
        if font_path and Path(font_path).exists():
            font_manager.fontManager.addfont(font_path)
            font_name = font_manager.FontProperties(fname=font_path).get_name()
            plt.rcParams["font.family"] = font_name
            break
    else:
        # Last-resort fallback; charts still render even if Korean glyphs are missing.
        plt.rcParams["font.family"] = "DejaVu Sans"
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


def sanitize_cycle_report_html(value: str) -> str:
    """Allow simple report markup while removing dangerous tags/attributes."""
    value = re.sub(r"<\s*(script|style)[^>]*>.*?<\s*/\s*\1\s*>", "", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"\s+on[a-zA-Z]+\s*=\s*(['\"]).*?\1", "", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"\s+(href|src)\s*=\s*(['\"])\s*javascript:.*?\2", "", value, flags=re.IGNORECASE | re.DOTALL)
    allowed = {"h3", "h4", "p", "strong", "em", "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td", "br", "blockquote"}

    def clean_tag(match: re.Match) -> str:
        closing, tag = match.group(1), match.group(2).lower()
        if tag not in allowed:
            return ""
        return f"<{closing}{tag}>"

    return re.sub(r"<\s*(/?)\s*([a-zA-Z0-9]+)(?:\s+[^>]*)?>", clean_tag, value).strip()


def action_items_html(items: list[str]) -> str:
    return "\n".join(f"        <li>{html.escape(item)}</li>" for item in items if item.strip())


def load_cycle_analysis(today: datetime, path: Path = CYCLE_ANALYSIS_FILE) -> dict:
    analysis = dict(DEFAULT_CYCLE_ANALYSIS)
    if not path.exists():
        return analysis
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return analysis
    if raw.get("date") != today.strftime("%Y-%m-%d"):
        return analysis
    for key in ["headline", "summary_line", "cycle_summary", "chart_caption"]:
        value = str(raw.get(key, "")).strip()
        if value:
            analysis[key] = html.escape(value)
    report_html = str(raw.get("report_html", "")).strip()
    if report_html:
        analysis["report_html"] = sanitize_cycle_report_html(report_html)
    raw_action_items = raw.get("action_items")
    if isinstance(raw_action_items, list):
        action_items = []
        for item in raw_action_items:
            clean = sanitize_cycle_report_html(str(item)).strip()
            if clean:
                action_items.append(clean)
        if action_items:
            analysis["action_items"] = action_items[:6]
    analysis["source"] = raw.get("source", "daily_research")
    return analysis


def write_summary_json(rows: list[PriceRow], macro: dict, today: datetime, out: Path, cycle_analysis: dict | None = None) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    cycle_analysis = cycle_analysis or DEFAULT_CYCLE_ANALYSIS
    payload = {
        "date": today.strftime("%Y-%m-%d"),
        "site_url": "https://js1876.github.io/daily-briefing/public/",
        "latest_url": "https://js1876.github.io/daily-briefing/public/latest.html",
        "cycle_summary": html.unescape(cycle_analysis["cycle_summary"]),
        "cycle_headline": html.unescape(cycle_analysis["headline"]),
        "action_items": [html.unescape(item) for item in cycle_analysis.get("action_items", [])],
        "prices": [
            {
                "ticker": row.ticker,
                "name": row.name,
                "close": row.close,
                "prev_close": row.prev_close,
                "change": row.change,
                "change_pct": row.change_pct,
                "basis_date": row.basis_date.strftime("%Y-%m-%d"),
            }
            for row in rows
        ],
        "macro": macro,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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
    return """
    :root {
      --bg: #f6f7f9;
      --panel: #ffffff;
      --line: #e5e7eb;
      --text: #171717;
      --muted: #667085;
      --up: #d62728;
      --down: #1f77b4;
      --accent: #0f766e;
      --soft: #f8fafc;
      --shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
    }

    * { box-sizing: border-box; }

    html, body { max-width: 100%; overflow-x: hidden; }

    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", Arial, sans-serif;
      line-height: 1.55;
      word-break: keep-all;
      overflow-wrap: anywhere;
    }

    main {
      width: min(1180px, calc(100% - 32px));
      margin: 0 auto;
      padding: 28px 0 48px;
    }

    header { display: grid; gap: 10px; margin-bottom: 18px; }

    h1 { margin: 0; font-size: clamp(26px, 4vw, 42px); line-height: 1.18; }
    h2 { margin: 0 0 16px; font-size: 22px; line-height: 1.28; }
    h3 { margin: 18px 0 10px; font-size: 18px; line-height: 1.35; }
    p { margin: 0 0 12px; }
    a { color: #155eef; text-decoration: none; }
    a:hover { text-decoration: underline; }

    .meta { color: var(--muted); font-size: 14px; }

    .summary {
      display: grid;
      grid-template-columns: 1.6fr 1fr 1fr;
      gap: 12px;
      margin: 18px 0 22px;
    }

    .tile, section, .stock-news {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      box-shadow: var(--shadow);
    }

    .tile { padding: 18px; min-height: 96px; }
    .tile-label { color: var(--muted); font-size: 13px; margin-bottom: 6px; }
    .tile-value { font-size: clamp(20px, 4.8vw, 24px); font-weight: 800; line-height: 1.25; }

    section { padding: 22px; margin: 16px 0; overflow: hidden; }

    .table-wrap { width: 100%; overflow-x: visible; }

    table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      font-size: 15px;
    }

    th, td {
      padding: 12px 10px;
      border-bottom: 1px solid var(--line);
      text-align: right;
      vertical-align: top;
      white-space: normal;
      overflow-wrap: anywhere;
    }

    th:first-child, td:first-child { text-align: left; }
    th { color: var(--muted); font-size: 13px; font-weight: 700; background: #fafafa; }

    .price-table th:nth-child(1), .price-table td:nth-child(1) { width: 32%; }
    .price-table th:nth-child(2), .price-table td:nth-child(2) { width: 12%; }
    .price-table th:nth-child(3), .price-table td:nth-child(3),
    .price-table th:nth-child(4), .price-table td:nth-child(4) { width: 18%; }
    .price-table th:nth-child(5), .price-table td:nth-child(5),
    .price-table th:nth-child(6), .price-table td:nth-child(6) { width: 10%; }

    .cycle-report table { margin: 12px 0 18px; }
    .cycle-report th, .cycle-report td { line-height: 1.5; }
    .cycle-report ul, .cycle-report ol { padding-left: 22px; }
    .cycle-report li { margin: 6px 0; }

    .up { color: var(--up); font-weight: 800; }
    .down { color: var(--down); font-weight: 800; }

    .charts { display: grid; grid-template-columns: 1fr; gap: 18px; }
    figure { margin: 0; background: #fff; border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
    figure img { display: block; width: 100%; height: auto; }
    figcaption { padding: 12px 14px; border-top: 1px solid var(--line); color: var(--muted); font-size: 13px; }

    .text-bars { display: grid; gap: 10px; margin-top: 10px; }
    .bar-row { display: grid; grid-template-columns: 210px 72px 1fr; gap: 12px; align-items: center; font-size: 14px; }
    .bar-track { height: 12px; background: #eef2f7; border-radius: 999px; overflow: hidden; }
    .bar-fill { height: 100%; border-radius: 999px; }
    .bar-fill.up-bg { background: var(--up); }
    .bar-fill.down-bg { background: var(--down); }

    .news-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
    .stock-news { padding: 18px; box-shadow: none; }
    .stock-news ol { margin: 8px 0 0 20px; padding: 0; }
    .stock-news li { margin: 0 0 12px; padding-left: 4px; }
    .source { display: block; color: var(--muted); font-size: 13px; margin-bottom: 3px; }
    .empty { color: var(--muted); background: #f9fafb; border: 1px dashed #d0d5dd; border-radius: 8px; padding: 14px; }
    .actions { display: grid; gap: 10px; margin: 0; padding-left: 20px; }
    .note { color: var(--muted); font-size: 14px; margin-top: 12px; }

    @media (max-width: 840px) {
      .summary, .news-grid { grid-template-columns: 1fr; }
      .bar-row { grid-template-columns: 1fr; gap: 6px; }
    }

    @media (max-width: 640px) {
      main { width: min(100% - 24px, 100%); padding: 18px 0 36px; }
      section { padding: 18px 14px; border-radius: 12px; }
      h2 { font-size: 21px; }
      .tile { padding: 16px; }

      .price-table, .price-table thead, .price-table tbody, .price-table tr {
        display: block;
        width: 100%;
      }

      .price-table thead { display: none; }

      .price-table tr {
        padding: 16px 0;
        border-bottom: 1px solid var(--line);
      }

      .price-table td,
      .price-table td:nth-child(n) {
        display: grid;
        grid-template-columns: 92px minmax(0, 1fr);
        gap: 12px;
        align-items: baseline;
        width: 100% !important;
        border: 0;
        padding: 7px 0;
        text-align: right;
        min-width: 0;
        font-size: 15px;
        white-space: normal;
        word-break: keep-all;
        overflow-wrap: normal;
      }

      .price-table td::before {
        content: attr(data-label);
        color: var(--muted);
        font-size: 13px;
        font-weight: 700;
        text-align: left;
        white-space: nowrap;
      }

      .price-table td:first-child {
        display: block;
        text-align: left;
        font-size: 22px;
        font-weight: 800;
        line-height: 1.35;
        padding-bottom: 12px;
        word-break: keep-all;
        overflow-wrap: normal;
      }

      .price-table td:first-child::before {
        display: block;
        margin-bottom: 4px;
      }

      .cycle-report table, .cycle-report thead, .cycle-report tbody, .cycle-report tr, .cycle-report th, .cycle-report td {
        display: block;
        width: 100%;
      }

      .cycle-report thead { display: none; }
      .cycle-report tr {
        margin: 0 0 12px;
        padding: 12px;
        border: 1px solid var(--line);
        border-radius: 10px;
        background: var(--soft);
      }
      .cycle-report th, .cycle-report td {
        border: 0;
        padding: 4px 0;
        text-align: left;
        font-size: 14px;
        white-space: normal;
        overflow-wrap: anywhere;
      }

      .charts figure { overflow: visible; }
      figcaption { font-size: 12px; }
    }
  """


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


def render_html(rows: list[PriceRow], news: dict, macro: dict, valuation: dict, today: datetime, chart_files: dict, cycle_analysis: dict | None = None) -> str:
    cycle_analysis = cycle_analysis or DEFAULT_CYCLE_ANALYSIS
    css = css_from_existing()
    basis_date = rows[0].basis_date.strftime("%Y-%m-%d")
    today_s = today.strftime("%Y-%m-%d")
    up_count = sum(1 for row in rows if row.change_pct >= 0)
    down_count = len(rows) - up_count
    max_row = max(rows, key=lambda row: abs(row.change_pct))
    max_up = max(rows, key=lambda row: row.change_pct)
    max_down = min(rows, key=lambda row: row.change_pct)

    summary_line = cycle_analysis["summary_line"]
    table_rows = "\n".join(
        f"""
            <tr>
              <td data-label="종목">{html.escape(row.name)}</td>
              <td data-label="티커">{row.ticker}</td>
              <td data-label="기준 가격">{money_krw(row.close)}</td>
              <td data-label="전 거래일">{money_krw(row.prev_close)}</td>
              <td data-label="등락" class="{'up' if row.change >= 0 else 'down'}">{signed_money(row.change)}</td>
              <td data-label="변동률" class="{'up' if row.change_pct >= 0 else 'down'}">{signed_pct(row.change_pct)}</td>
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
    action_items = action_items_html(cycle_analysis.get("action_items", DEFAULT_CYCLE_ANALYSIS["action_items"]))

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
        <div class="tile-value">{cycle_analysis['headline']}</div>
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
        <table class="price-table">
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
        <figcaption>{cycle_analysis['chart_caption']}</figcaption>
      </figure>
    </section>

    <section>
      <h2>반도체 섹터 투자 분석 리포트</h2>
      <p class="meta">분석 대상: 삼성전자, SK하이닉스, TIGER 반도체TOP10, KODEX 200타겟위클리커버드콜 | 데이터 기준: {basis_date} 종가 및 {today_s} 확인 자료</p>

      <div class="cycle-report">
      {cycle_analysis['report_html']}
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
{action_items}
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
    cycle_analysis = load_cycle_analysis(today)

    chart_files = {
        "change": f"assets/charts/daily_briefing_change_chart_{date_slug}.png",
        "trend": f"assets/charts/daily_briefing_price_trends_{date_slug}.png",
        "cycle": f"assets/charts/daily_briefing_semiconductor_cycle_{date_slug}.png",
    }
    save_change_chart(rows, PUBLIC_DIR / chart_files["change"])
    save_price_trends(rows, PUBLIC_DIR / chart_files["trend"])
    save_cycle_chart(PUBLIC_DIR / chart_files["cycle"])

    rendered = render_html(rows, news, macro, valuation, today, chart_files, cycle_analysis)
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
    write_summary_json(rows, macro, today, LOG_DIR / "latest_summary.json", cycle_analysis)

    print(latest)
    print(index)
    print(dated)
    print(public_dated)
    print(bundle)


if __name__ == "__main__":
    main()
