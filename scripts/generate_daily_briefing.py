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
    ax.text(0.99, -0.13, f"기준: {basis} 최신 확인가 / 전 기준가 대비", transform=ax.transAxes, ha="right", va="top", fontsize=10, color=MUTED)
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
            f"최근 확인가 {format_krw_short(row.close)}  |  {signed_pct(row.change_pct)}",
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
    fig.suptitle("종목별 최근 4거래일 가격 흐름", fontsize=19, fontweight="bold", color=TEXT, y=0.99)
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
      --bg: #eef3f8;
      --bg2: #f8fbff;
      --surface: rgba(255, 255, 255, 0.78);
      --surface-elevated: #ffffff;
      --surface-muted: #f4f7fb;
      --text: #101828;
      --text-muted: #667085;
      --border: rgba(15, 23, 42, 0.10);
      --accent: #2563eb;
      --accent-strong: #1d4ed8;
      --accent-soft: rgba(37, 99, 235, 0.11);
      --up: #d92d20;
      --down: #2563eb;
      --neutral: #64748b;
      --shadow: 0 20px 55px rgba(30, 41, 59, 0.10);
      --shadow-soft: 0 10px 28px rgba(15, 23, 42, 0.055);
      --radius-xl: 32px;
      --radius-lg: 24px;
      --radius-md: 18px;
      --space: clamp(14px, 2.4vw, 28px);
      --content-max: 1320px;
      --chart-bg: #ffffff;
      --bar-track: #e5edf7;
      color-scheme: light;

      /* backward-compatible aliases used by older generated fragments */
      --panel: var(--surface-elevated);
      --panel-soft: var(--surface-muted);
      --line: var(--border);
      --muted: var(--text-muted);
      --hero-panel: var(--surface);
      --body-end: #f9fafb;
      --card-shadow: var(--shadow-soft);
      --summary-text: #344054;
    }

    html[data-theme="dark"] {
      --bg: #07111f;
      --bg2: #111827;
      --surface: rgba(17, 28, 47, 0.78);
      --surface-elevated: #111c2f;
      --surface-muted: #17243a;
      --text: #edf4ff;
      --text-muted: #a7b4c8;
      --border: rgba(148, 163, 184, 0.20);
      --accent: #7dd3fc;
      --accent-strong: #38bdf8;
      --accent-soft: rgba(125, 211, 252, 0.15);
      --up: #ff7a70;
      --down: #60a5fa;
      --neutral: #94a3b8;
      --shadow: 0 24px 60px rgba(0, 0, 0, 0.36);
      --shadow-soft: 0 14px 34px rgba(0, 0, 0, 0.24);
      --chart-bg: #f8fafc;
      --bar-track: #26364f;
      --body-end: #09111f;
      --summary-text: #cbd5e1;
      color-scheme: dark;
    }

    *, *::before, *::after { box-sizing: border-box; }
    html, body { width: 100%; max-width: 100%; overflow-x: hidden; }
    body {
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(circle at 10% -8%, rgba(37,99,235,.18), transparent 30%),
        radial-gradient(circle at 88% 12%, rgba(125,211,252,.13), transparent 26%),
        linear-gradient(180deg, var(--bg) 0%, var(--bg2) 48%, var(--body-end) 100%);
      color: var(--text);
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Display", "Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic", sans-serif;
      line-height: 1.66;
      word-break: keep-all;
      overflow-wrap: anywhere;
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
    }
    img, svg, canvas, video { display: block; max-width: 100%; height: auto; }
    p, li, span, div, a, h1, h2, h3, h4 { overflow-wrap: anywhere; word-break: keep-all; }
    a { color: var(--accent-strong); text-decoration: none; }
    a:hover { text-decoration: underline; }
    main { width: min(var(--content-max), calc(100% - clamp(24px, 5vw, 56px))); margin: 0 auto; padding: clamp(14px, 2.2vw, 28px) 0 clamp(44px, 6vw, 76px); }
    .section, .card, .stock-card, .factor-card, .news-card, .action-card, .company-card, .hero-card, .chart-card, .cycle-card, .check-card, .metric-card, .side-card { min-width: 0; }

    .topbar { display: flex; justify-content: flex-end; margin: 4px 0 12px; }
    .theme-toggle {
      display: inline-flex; align-items: center; gap: 8px; min-height: 44px;
      border: 1px solid var(--border); border-radius: 999px; padding: 10px 14px;
      background: color-mix(in srgb, var(--surface-elevated) 84%, transparent);
      color: var(--text); box-shadow: var(--shadow-soft); font: inherit; font-size: 13px; font-weight: 850; cursor: pointer;
      backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px); transition: transform .18s ease, background .18s ease, border-color .18s ease;
    }
    .theme-toggle:hover { transform: translateY(-1px); }
    .theme-toggle:focus-visible { outline: 3px solid var(--accent-soft); outline-offset: 3px; }
    .theme-icon { font-size: 15px; line-height: 1; }

    .dashboard-shell { display: grid; gap: var(--space); align-items: start; }
    .main-column, .side-column { display: grid; gap: var(--space); min-width: 0; }
    .side-column { align-content: start; }

    .hero-card, .section, .side-card {
      background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-xl); box-shadow: var(--shadow);
      backdrop-filter: blur(22px); -webkit-backdrop-filter: blur(22px);
    }
    .hero-card { padding: clamp(22px, 5vw, 44px); overflow: hidden; position: relative; }
    .hero-card::after { content: ""; position: absolute; inset: auto -18% -38% 36%; height: 180px; border-radius: 999px; background: rgba(37,99,235,.12); filter: blur(34px); pointer-events: none; }
    .hero-content { position: relative; z-index: 1; display: grid; gap: 12px; }
    .eyebrow, .section-kicker, .card-label { color: var(--accent-strong); font-size: 12px; font-weight: 900; letter-spacing: .045em; text-transform: uppercase; }
    h1 { margin: 0; font-size: clamp(32px, 8vw, 64px); line-height: .98; letter-spacing: -.06em; }
    h2 { margin: 0; font-size: clamp(22px, 4vw, 34px); line-height: 1.12; letter-spacing: -.045em; }
    h3 { margin: 0; font-size: clamp(17px, 2vw, 21px); line-height: 1.28; letter-spacing: -.025em; }
    p { margin: 0; }
    .meta, .muted { color: var(--text-muted); font-size: clamp(13px, 1.5vw, 14px); }
    .hero-summary { color: var(--summary-text); font-size: clamp(15px, 2.1vw, 18px); max-width: 860px; }
    .hero-summary strong { color: var(--text); font-size: clamp(18px, 3vw, 28px); letter-spacing: -.035em; }

    .badge-row, .tag-row, .metric-row { display: flex; flex-wrap: wrap; gap: 8px; min-width: 0; }
    .badge, .tag {
      display: inline-flex; align-items: center; gap: 5px; max-width: 100%; border-radius: 999px; padding: 7px 11px;
      background: var(--accent-soft); color: var(--accent-strong); font-size: 12px; font-weight: 850; border: 1px solid color-mix(in srgb, var(--accent) 22%, transparent);
    }
    .badge.neutral { background: var(--surface-muted); color: var(--text-muted); border-color: var(--border); }
    .badge.up, .tag.up { background: rgba(255, 107, 107, .13); color: var(--up); border-color: rgba(255,107,107,.20); }
    .badge.down, .tag.down { background: rgba(96, 165, 250, .14); color: var(--down); border-color: rgba(96,165,250,.24); }

    .section, .side-card { padding: clamp(18px, 3vw, 30px); }
    .section-head { display: flex; flex-direction: column; gap: 7px; margin-bottom: clamp(14px, 2.4vw, 22px); }
    .section-subtitle { max-width: 760px; }

    .metric-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 8px; }
    .metric-card { background: var(--surface-elevated); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 13px; box-shadow: var(--shadow-soft); }
    .metric-value { font-size: clamp(22px, 5vw, 32px); font-weight: 950; letter-spacing: -.045em; line-height: 1; margin-top: 5px; }

    .stock-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 238px), 1fr)); gap: clamp(12px, 2vw, 18px); }
    .company-grid, .chart-grid { display: grid; grid-template-columns: 1fr; gap: clamp(12px, 2vw, 18px); }
    .factor-grid { display: grid; grid-template-columns: 1fr; gap: 12px; }
    .stock-card, .company-card, .factor-card, .chart-card, .cycle-card, .news-card, .check-card, .metric-card, .report-card {
      background: var(--surface-elevated); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: clamp(15px, 2.4vw, 20px); box-shadow: var(--shadow-soft);
      transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
    }
    .stock-card:hover, .company-card:hover, .factor-card:hover, .news-card:hover { transform: translateY(-2px); border-color: color-mix(in srgb, var(--accent) 24%, var(--border)); }
    .stock-card { container-type: inline-size; display: grid; gap: 13px; }
    .stock-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
    .stock-name { font-size: clamp(18px, 4vw, 22px); font-weight: 950; letter-spacing: -.04em; }
    .ticker { color: var(--text-muted); font-size: 12px; font-weight: 850; margin-top: 2px; }
    .price-box { text-align: right; flex: 0 0 auto; }
    .price { font-size: clamp(20px, 5vw, 28px); font-weight: 950; letter-spacing: -.045em; white-space: nowrap; line-height: 1.05; }
    .change-line { font-size: 13px; font-weight: 900; white-space: nowrap; }
    .up { color: var(--up); }
    .down { color: var(--down); }
    .stock-summary, .company-copy, .factor-copy, .cycle-copy { color: var(--summary-text); font-size: 15px; margin-top: 2px; line-height: 1.62; }

    .mini-bars { display: grid; gap: 12px; }
    .mini-bar-row { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 10px; align-items: center; font-size: 14px; }
    .bar-track { grid-column: 1 / -1; height: 10px; border-radius: 999px; background: var(--bar-track); overflow: hidden; }
    .bar-fill { height: 100%; border-radius: 999px; }
    .bar-fill.up-bg { background: var(--up); }
    .bar-fill.down-bg { background: var(--down); }

    figure { margin: 0; }
    .chart-card { overflow: hidden; }
    .chart-card img { width: 100%; border-radius: 20px; background: var(--chart-bg); }
    figcaption { margin-top: 10px; color: var(--text-muted); font-size: 13px; }

    .cycle-card { display: grid; gap: clamp(14px, 2vw, 22px); }
    .cycle-grid { display: grid; grid-template-columns: 1fr; gap: 10px; }
    .cycle-point { background: var(--surface-muted); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 13px; }
    .cycle-point strong { display: block; margin-bottom: 4px; color: var(--text); }
    details.detail-pack { border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--surface-muted); padding: 4px; }
    details.detail-pack > summary { cursor: pointer; list-style: none; padding: 13px 14px; font-weight: 900; color: var(--text); }
    details.detail-pack > summary::-webkit-details-marker { display: none; }
    details.detail-pack > summary::after { content: "＋"; float: right; color: var(--accent-strong); }
    details.detail-pack[open] > summary::after { content: "－"; }
    .cycle-report { display: grid; gap: 12px; padding: 0 10px 12px; }
    .report-card { border-radius: var(--radius-md); display: grid; gap: 8px; }
    .report-field { display: grid; gap: 3px; font-size: 14px; line-height: 1.58; }
    .report-field strong { color: var(--text-muted); font-size: 12px; }
    .cycle-report table { display: block; width: 100%; border: 0; }
    .cycle-report thead { display: none; }
    .cycle-report tbody, .cycle-report tr, .cycle-report th, .cycle-report td { display: block; width: 100%; }

    .company-card { display: grid; gap: 12px; }
    .company-card .position { width: fit-content; }
    .split-list { display: grid; gap: 8px; }
    .split-list div { background: var(--surface-muted); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 11px; font-size: 14px; }
    .split-list strong { display: block; margin-bottom: 3px; color: var(--text); }
    .checkpoint-row { display: flex; flex-wrap: wrap; gap: 8px; }

    .factor-card { display: grid; gap: 8px; }
    .factor-value { font-size: clamp(22px, 5vw, 30px); font-weight: 950; letter-spacing: -.045em; line-height: 1.05; }

    .news-timeline { display: grid; gap: 10px; }
    .news-card { position: relative; padding-left: 20px; }
    .news-card::before { content: ""; position: absolute; left: 8px; top: 22px; width: 8px; height: 8px; border-radius: 999px; background: var(--accent-strong); box-shadow: 0 0 0 5px var(--accent-soft); }
    .news-meta { color: var(--text-muted); font-size: 12px; margin-bottom: 5px; }
    .news-title { display: block; font-size: 15px; font-weight: 850; line-height: 1.48; }
    .news-desc { margin-top: 6px; color: var(--summary-text); font-size: 13px; }

    .check-card { background: linear-gradient(180deg,var(--surface-elevated) 0%,var(--surface-muted) 100%); }
    .check-list { display: grid; gap: 10px; margin: 12px 0 0; padding: 0; list-style: none; }
    .check-item { display: grid; grid-template-columns: 26px minmax(0,1fr); gap: 11px; align-items: start; background: var(--surface-elevated); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 13px; font-size: 15px; min-height: 48px; }
    .check-box { width: 19px; height: 19px; border: 2px solid var(--accent-strong); border-radius: 7px; margin-top: 2px; background: var(--accent-soft); }
    .footer-note { color: var(--text-muted); font-size: 12px; margin-top: 14px; }

    @container (min-width: 360px) {
      .stock-card { grid-template-rows: auto 1fr auto; }
    }
    @media (min-width: 720px) {
      .metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .company-grid, .chart-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .factor-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .cycle-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (min-width: 1100px) {
      .dashboard-shell { grid-template-columns: minmax(0, 2fr) minmax(320px, .82fr); }
      .side-column { align-self: start; padding-right: 2px; }
      .hero-card { min-height: 360px; display: flex; align-items: end; }
      .side-column .section { padding: 20px; border-radius: 26px; }
      .side-column h2 { font-size: 22px; }
      .stock-grid { grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); }
    }
    @media (max-width: 520px) {
      main { width: min(100% - 24px, 100%); }
      .metric-grid { grid-template-columns: 1fr; }
      .stock-top { flex-direction: column; }
      .price-box { text-align: left; }
      .side-column { gap: 16px; }
      .hero-card, .section { border-radius: 26px; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; scroll-behavior: auto !important; transition-duration: 0.01ms !important; }
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



def strip_tags(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def cycle_report_cards_html(report_html: str) -> str:
    def table_to_cards(match: re.Match) -> str:
        table = match.group(0)
        rows = re.findall(r"<tr>(.*?)</tr>", table, flags=re.IGNORECASE | re.DOTALL)
        if not rows:
            return ""
        headers = [strip_tags(cell) for cell in re.findall(r"<t[hd]>(.*?)</t[hd]>", rows[0], flags=re.IGNORECASE | re.DOTALL)]
        body_rows = rows[1:] if headers else rows
        cards = []
        for row in body_rows:
            cells = [strip_tags(cell) for cell in re.findall(r"<t[hd]>(.*?)</t[hd]>", row, flags=re.IGNORECASE | re.DOTALL)]
            if not any(cells):
                continue
            fields = []
            for idx, cell in enumerate(cells):
                label = headers[idx] if idx < len(headers) and headers[idx] else f"항목 {idx + 1}"
                fields.append(f'<div class="report-field"><strong>{html.escape(label)}</strong><span>{html.escape(cell)}</span></div>')
            cards.append(f'<article class="report-card">{"".join(fields)}</article>')
        return "".join(cards)

    return re.sub(r"<table>.*?</table>", table_to_cards, report_html, flags=re.IGNORECASE | re.DOTALL)


def stock_tags(row: PriceRow) -> list[str]:
    tags = []
    if "삼성" in row.name:
        tags = ["HBM 추격", "NAND", "파운드리"]
    elif "하이닉스" in row.name:
        tags = ["HBM 순도", "AI 서버", "DRAM"]
    elif "TIGER" in row.name:
        tags = ["반도체 ETF", "대형주", "분산"]
    elif "KODEX" in row.name:
        tags = ["커버드콜", "분배", "방어"]
    else:
        tags = ["포트폴리오", "관찰"]
    tags.append("상승" if row.change_pct >= 0 else "하락")
    return tags[:4]


def stock_summary(row: PriceRow) -> str:
    direction = "상승" if row.change_pct >= 0 else "하락"
    if "삼성" in row.name:
        base = "HBM·NAND·파운드리 회복 기대와 수급 변화를 함께 확인할 종목입니다."
    elif "하이닉스" in row.name:
        base = "HBM 노출도가 높아 AI 메모리 사이클을 가장 직접적으로 반영합니다."
    elif "TIGER" in row.name:
        base = "반도체 대형주 흐름을 묶어서 보는 섹터 온도계 역할입니다."
    elif "KODEX" in row.name:
        base = "분배와 변동성 완충 목적의 보유 성격이 강한 상품입니다."
    else:
        base = "포트폴리오 내 상대 강도와 수급을 함께 확인합니다."
    return f"오늘은 {direction} 마감했습니다. {base}"


def stock_cards_html(rows: list[PriceRow]) -> str:
    cards = []
    for row in rows:
        direction = "up" if row.change_pct >= 0 else "down"
        tags = "".join(f'<span class="tag {direction}">{html.escape(tag)}</span>' for tag in stock_tags(row))
        cards.append(f"""
        <article class="stock-card">
          <div class="stock-top">
            <div>
              <h3 class="stock-name">{html.escape(row.name)}</h3>
              <div class="ticker">{row.ticker}</div>
            </div>
            <div class="price-box">
              <div class="price">{money_krw(row.close)}</div>
              <div class="change-line {direction}">{signed_money(row.change)} · {signed_pct(row.change_pct)}</div>
            </div>
          </div>
          <div class="tag-row">{tags}</div>
          <p class="stock-summary">{html.escape(stock_summary(row))}</p>
        </article>""")
    return "\n".join(cards)


def text_bars_html(rows: list[PriceRow]) -> str:
    max_abs = max(max(abs(row.change_pct) for row in rows), 0.01)
    parts = []
    for row in sorted(rows, key=lambda r: r.change_pct, reverse=True):
        direction = "up" if row.change_pct >= 0 else "down"
        parts.append(f"""
        <div class="mini-bar-row">
          <strong>{html.escape(row.name.replace('KODEX 200타겟위클리커버드콜', 'KODEX 커버드콜'))}</strong>
          <span class="{direction}">{'▲' if row.change_pct >= 0 else '▼'} {signed_pct(row.change_pct)}</span>
          <div class="bar-track"><div class="bar-fill {direction}-bg" style="width: {max(4, min(100, abs(row.change_pct) / max_abs * 100)):.0f}%"></div></div>
        </div>""")
    return "\n".join(parts)


def macro_factor_html(macro: dict) -> str:
    labels = {
        "원/달러": ("환율", "원", "외국인 수급과 반도체 대형주 투자심리에 직접 영향을 줍니다."),
        "미국 10년물": ("미국 10년물", "%", "성장주·AI 반도체 밸류에이션 할인율을 좌우합니다."),
        "WTI": ("유가", "달러", "비용 부담과 인플레이션 기대를 통해 금리 경로에 영향을 줍니다."),
        "KOSPI": ("KOSPI", "", "국내 위험자산 선호와 대형주 수급 배경을 보여줍니다."),
    }
    cards = []
    for key, (title, suffix, copy) in labels.items():
        data = macro.get(key, {})
        change = data.get("change_pct")
        direction = "up" if (change or 0) >= 0 else "down"
        cards.append(f"""
        <article class="factor-card">
          <div class="card-label">{html.escape(title)}</div>
          <div class="factor-value">{metric_text(data.get('value'), suffix)}</div>
          <div class="change-line {direction}">{metric_text_signed(change, '%')}</div>
          <p class="factor-copy">{html.escape(copy)}</p>
        </article>""")
    return "\n".join(cards)


def company_cards_html(rows: list[PriceRow], valuation: dict) -> str:
    specs = [
        ("삼성전자", "HBM 추격형 · 복합 회복형", "메모리, NAND, 파운드리까지 회복 레버리지가 넓습니다.", "HBM 경쟁력 확인과 파운드리 부담이 같이 남아 있습니다.", ["HBM 수주", "저가 매수", "파운드리 손익"]),
        ("SK하이닉스", "HBM 순도 우위", "AI 서버와 HBM 사이클을 가장 직접적으로 반영합니다.", "급등 후 밸류에이션 부담과 CAPEX 확대 속도를 확인해야 합니다.", ["HBM 가격", "거래대금", "고객 다변화"]),
    ]
    cards = []
    row_map = {row.name: row for row in rows}
    for name, position, strength, risk, checkpoints in specs:
        row = row_map.get(name)
        val = valuation.get(name, {})
        today = f"오늘 변동률은 {signed_pct(row.change_pct)}입니다." if row else "오늘 가격 데이터는 제한적입니다."
        chips = "".join(f'<span class="tag">{html.escape(point)}</span>' for point in checkpoints)
        cards.append(f"""
        <article class="company-card">
          <div>
            <h3>{html.escape(name)}</h3>
            <div class="badge neutral position">{html.escape(position)}</div>
          </div>
          <div class="checkpoint-row" aria-label="핵심 체크포인트">{chips}</div>
          <div class="split-list">
            <div><strong>강점</strong>{html.escape(strength)}</div>
            <div><strong>리스크</strong>{html.escape(risk)}</div>
          </div>
          <details class="detail-pack company-detail">
            <summary>오늘의 해석 자세히 보기</summary>
            <div class="split-list">
              <div><strong>오늘의 해석</strong>{html.escape(today)} 시총 {cap_text(val.get('market_cap'))}, Forward PE {metric_text(val.get('forward_pe'))} 기준으로 추세 지속성을 점검합니다.</div>
            </div>
          </details>
        </article>""")
    return "\n".join(cards)


def news_timeline_html(rows: list[PriceRow], news: dict) -> str:
    items = []
    name_by_ticker = {row.ticker: row.name for row in rows}
    for ticker, articles in news.items():
        for item in articles:
            items.append({**item, "stock": name_by_ticker.get(ticker, ticker)})
    items.sort(key=lambda item: item.get("time", ""), reverse=True)
    if not items:
        return '<article class="news-card"><div class="news-title">오늘자 뉴스가 아직 충분히 수집되지 않았습니다.</div><p class="muted">장중 업데이트와 원문 확인이 필요합니다.</p></article>'
    cards = []
    for item in items[:12]:
        cards.append(f"""
        <article class="news-card">
          <div class="news-meta">{html.escape(item.get('time',''))} · {html.escape(item.get('source',''))} · {html.escape(item.get('stock',''))}</div>
          <a class="news-title" href="{html.escape(item.get('link',''))}">{html.escape(item.get('title',''))}</a>
        </article>""")
    return "\n".join(cards)


def checklist_html(items: list[str]) -> str:
    clean_items = [item for item in items if str(item).strip()]
    return "\n".join(f'<li class="check-item"><span class="check-box" aria-hidden="true"></span><span>{html.escape(str(item))}</span></li>' for item in clean_items)



def summary_metrics_html(up_count: int, down_count: int, max_row: PriceRow, max_up: PriceRow, max_down: PriceRow) -> str:
    direction = "up" if max_row.change_pct >= 0 else "down"
    return f"""
      <div class="metric-grid dashboard-metrics">
        <article class="metric-card">
          <div class="card-label">상승 종목</div>
          <div class="metric-value up">{up_count}</div>
          <p class="muted">포트폴리오 내 상승 마감</p>
        </article>
        <article class="metric-card">
          <div class="card-label">하락 종목</div>
          <div class="metric-value down">{down_count}</div>
          <p class="muted">포트폴리오 내 하락 마감</p>
        </article>
        <article class="metric-card">
          <div class="card-label">최대 변동</div>
          <div class="metric-value {direction}">{signed_pct(max_row.change_pct)}</div>
          <p class="muted">{html.escape(max_row.name)} · 상승 {html.escape(max_up.name)} {signed_pct(max_up.change_pct)} / 하락 {html.escape(max_down.name)} {signed_pct(max_down.change_pct)}</p>
        </article>
      </div>"""


def render_html(rows: list[PriceRow], news: dict, macro: dict, valuation: dict, today: datetime, chart_files: dict, cycle_analysis: dict | None = None) -> str:
    cycle_analysis = cycle_analysis or DEFAULT_CYCLE_ANALYSIS
    css = css_from_existing()
    basis_date = rows[0].basis_date.strftime("%Y-%m-%d")
    checked_at = today.strftime("%Y-%m-%d %H:%M")
    today_s = today.strftime("%Y-%m-%d")
    up_count = sum(1 for row in rows if row.change_pct >= 0)
    down_count = len(rows) - up_count
    max_row = max(rows, key=lambda row: abs(row.change_pct))
    max_up = max(rows, key=lambda row: row.change_pct)
    max_down = min(rows, key=lambda row: row.change_pct)
    max_direction = "up" if max_row.change_pct >= 0 else "down"

    summary_line = cycle_analysis["summary_line"]
    stock_cards = stock_cards_html(rows)
    mini_bars = text_bars_html(rows)
    factor_cards = macro_factor_html(macro)
    company_cards = company_cards_html(rows, valuation)
    timeline = news_timeline_html(rows, news)
    checks = checklist_html(cycle_analysis.get("action_items", DEFAULT_CYCLE_ANALYSIS["action_items"]))
    metrics = summary_metrics_html(up_count, down_count, max_row, max_up, max_down)

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
    <div class="topbar">
      <button class="theme-toggle" type="button" aria-label="다크모드 전환" aria-pressed="false" data-theme-toggle>
        <span class="theme-icon" aria-hidden="true">🌙</span>
        <span class="theme-label">다크모드</span>
      </button>
    </div>

    <div class="dashboard-shell">
      <div class="main-column">
        <header class="hero-card">
          <div class="hero-content">
            <div class="eyebrow">DAILY SEMICONDUCTOR BRIEFING</div>
            <h1>일일 포트폴리오 브리핑</h1>
            <p class="meta">작성일: {today_s} KST · 가격 확인: {checked_at} KST · 표시 가격: 조회 시점 최신가</p>
            <div class="badge-row" aria-label="오늘 요약 지표">
              <span class="badge up">상승 {up_count}</span>
              <span class="badge down">하락 {down_count}</span>
              <span class="badge {max_direction}">최대 변동 {html.escape(max_row.name)} {signed_pct(max_row.change_pct)}</span>
              <span class="badge neutral">반도체 사이클 점검</span>
            </div>
            <p class="hero-summary"><strong>{cycle_analysis['headline']}</strong></p>
            <p class="hero-summary">{summary_line}</p>
            {metrics}
          </div>
        </header>

        <section class="section" aria-labelledby="stocks-title">
          <div class="section-head">
            <div class="section-kicker">Portfolio</div>
            <h2 id="stocks-title">오늘의 종목 브리핑</h2>
            <p class="meta section-subtitle">가격표 대신 종목별 앱 카드로 현재가, 등락, 핵심 태그와 한 줄 해석을 먼저 보여줍니다.</p>
          </div>
          <div class="stock-grid">{stock_cards}
          </div>
        </section>

        <section class="section" aria-labelledby="visual-title">
          <div class="section-head">
            <div class="section-kicker">Visual</div>
            <h2 id="visual-title">시각화 대시보드</h2>
            <p class="meta section-subtitle">기존 차트를 유지하면서 넓은 화면에서는 메인 분석 카드처럼, 모바일에서는 잘리지 않는 이미지 카드처럼 보이도록 배치했습니다.</p>
          </div>
          <div class="chart-grid">
            <figure class="chart-card">
              <img src="{chart_files['change']}" alt="전 거래일 대비 변동률 차트">
              <figcaption>전 거래일 대비 변동률 차트입니다.</figcaption>
            </figure>
            <figure class="chart-card">
              <img src="{chart_files['trend']}" alt="종목별 최근 4거래일 가격 흐름 차트">
              <figcaption>종목별 최근 4거래일 가격 흐름입니다.</figcaption>
            </figure>
          </div>
        </section>

        <section class="section" aria-labelledby="cycle-title">
          <div class="section-head">
            <div class="section-kicker">Cycle Check</div>
            <h2 id="cycle-title">사이클 진단</h2>
            <p class="meta section-subtitle">모바일에서는 요약을 먼저 보고, 상세 근거는 접어서 확인하는 구조입니다.</p>
          </div>
          <article class="cycle-card">
            <figure class="chart-card">
              <img src="{chart_files['cycle']}" alt="반도체 메모리 사이클 위치 추정">
              <figcaption>{cycle_analysis['chart_caption']}</figcaption>
            </figure>
            <div class="cycle-grid">
              <div class="cycle-point"><strong>현재 구간</strong><span>{cycle_analysis['headline']}</span></div>
              <div class="cycle-point"><strong>판단</strong><span>{cycle_analysis['cycle_summary']}</span></div>
              <div class="cycle-point"><strong>근거</strong><span>가격 흐름, HBM 수요, 수급, 환율·금리·유가를 함께 확인합니다.</span></div>
              <div class="cycle-point"><strong>주의점</strong><span>급등 후 추격보다 장중 수급과 매크로 변화를 먼저 봅니다.</span></div>
            </div>
            <details class="detail-pack cycle-detail">
              <summary>상세 분석 카드 펼치기</summary>
              <div class="cycle-report">
                {cycle_report_cards_html(cycle_analysis['report_html'])}
              </div>
            </details>
          </article>
        </section>

        <section class="section" aria-labelledby="company-title">
          <div class="section-head">
            <div class="section-kicker">Company</div>
            <h2 id="company-title">기업별 분석</h2>
            <p class="meta section-subtitle">비교표 대신 각 기업의 포지션, 강점, 리스크, 체크포인트를 독립 카드로 정리했습니다.</p>
          </div>
          <div class="company-grid">{company_cards}
          </div>
        </section>
      </div>

      <aside class="side-column" aria-label="요약, 매크로, 뉴스, 액션 사이드 패널">
        <section class="section side-card" aria-labelledby="momentum-title">
          <div class="section-head">
            <div class="section-kicker">Snapshot</div>
            <h2 id="momentum-title">요약 지표</h2>
          </div>
          <div class="mini-bars">{mini_bars}
          </div>
        </section>

        <section class="section side-card" aria-labelledby="macro-title">
          <div class="section-head">
            <div class="section-kicker">Macro</div>
            <h2 id="macro-title">매크로 팩터</h2>
          </div>
          <div class="factor-grid">{factor_cards}
          </div>
        </section>

        <section class="section side-card" aria-labelledby="news-title">
          <div class="section-head">
            <div class="section-kicker">News</div>
            <h2 id="news-title">뉴스 타임라인</h2>
            <p class="meta">KST 기준 {today_s} 발행분입니다.</p>
          </div>
          <div class="news-timeline">{timeline}
          </div>
        </section>

        <section class="section side-card action-card" aria-labelledby="actions-title">
          <article class="check-card">
            <div class="section-head">
              <div class="section-kicker">Action</div>
              <h2 id="actions-title">오늘의 액션</h2>
              <p class="meta">장 시작 전 체크리스트처럼 확인하세요.</p>
            </div>
            <ul class="check-list">
              {checks}
            </ul>
            <p class="footer-note">이 파일은 자동 생성 결과입니다. 투자 판단 전 원문 뉴스와 실시간 호가를 다시 확인하세요.</p>
          </article>
        </section>
      </aside>
    </div>
  </main>

  <script>
    (() => {{
      const root = document.documentElement;
      const button = document.querySelector('[data-theme-toggle]');
      const storageKey = 'daily-briefing-theme';
      const preferred = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
      const saved = localStorage.getItem(storageKey);
      const setTheme = (theme) => {{
        root.dataset.theme = theme;
        localStorage.setItem(storageKey, theme);
        const isDark = theme === 'dark';
        if (button) {{
          button.setAttribute('aria-pressed', String(isDark));
          button.querySelector('.theme-icon').textContent = isDark ? '☀️' : '🌙';
          button.querySelector('.theme-label').textContent = isDark ? '라이트모드' : '다크모드';
        }}
      }};
      setTheme(saved || preferred);
      button?.addEventListener('click', () => setTheme(root.dataset.theme === 'dark' ? 'light' : 'dark'));
    }})();
  </script>
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
