from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager


OUT_DIR = Path(".")
FONT_PATH = "C:/Windows/Fonts/malgun.ttf"

STOCKS = [
    {
        "name": "삼성전자",
        "ticker": "005930",
        "close": [299500, 317000, 349000, 360500],
        "change_pct": 3.30,
    },
    {
        "name": "KODEX 커버드콜",
        "ticker": "498400",
        "close": [25655, 26545, 27800, 27825],
        "change_pct": 0.09,
    },
    {
        "name": "SK하이닉스",
        "ticker": "000660",
        "close": [2289000, 2333000, 2363000, 2360000],
        "change_pct": -0.13,
    },
    {
        "name": "TIGER 반도체TOP10",
        "ticker": "396500",
        "close": [50115, 50450, 52505, 52085],
        "change_pct": -0.80,
    },
]

DATES = ["5/28", "5/29", "6/1", "6/2"]
UP = "#d62728"
DOWN = "#1f77b4"
TEXT = "#202124"
MUTED = "#6b7280"
GRID = "#e5e7eb"


def setup_font() -> None:
    font_manager.fontManager.addfont(FONT_PATH)
    font_name = font_manager.FontProperties(fname=FONT_PATH).get_name()
    plt.rcParams["font.family"] = font_name
    plt.rcParams["axes.unicode_minus"] = False


def format_krw(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}백만원"
    return f"{value:,}원"


def save_change_chart() -> Path:
    sorted_stocks = sorted(STOCKS, key=lambda item: item["change_pct"])
    names = [item["name"] for item in sorted_stocks]
    values = [item["change_pct"] for item in sorted_stocks]
    colors = [UP if value >= 0 else DOWN for value in values]

    fig, ax = plt.subplots(figsize=(11.5, 5.8), dpi=170)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    bars = ax.barh(names, values, color=colors, height=0.56)
    ax.axvline(0, color="#111827", linewidth=1.1)
    ax.grid(axis="x", color=GRID, linewidth=1, linestyle="-")
    ax.set_axisbelow(True)

    ax.set_title("전 거래일 대비 변동률", fontsize=19, fontweight="bold", color=TEXT, pad=18)
    ax.set_xlabel("변동률 (%)", fontsize=12, color=MUTED)
    ax.tick_params(axis="y", labelsize=12)
    ax.tick_params(axis="x", labelsize=11, colors=MUTED)
    ax.set_xlim(-1.15, 3.75)

    label_x = 3.45
    for bar, value, color in zip(bars, values, colors):
        ax.text(
            label_x,
            bar.get_y() + bar.get_height() / 2,
            f"{value:+.2f}%",
            va="center",
            ha="left",
            fontsize=13,
            fontweight="bold",
            color=color,
        )

    for spine in ["top", "right", "left"]:
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(GRID)

    ax.text(
        0.99,
        -0.13,
        "기준: 2026-06-02 종가 / 2026-06-01 종가 대비",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=10,
        color=MUTED,
    )

    out = OUT_DIR / "daily_briefing_change_chart_2026-06-03.png"
    fig.tight_layout(rect=[0.02, 0.04, 1, 0.98])
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def save_price_trends() -> Path:
    fig, axes = plt.subplots(2, 2, figsize=(12.5, 7.2), dpi=170)
    fig.patch.set_facecolor("white")
    axes = axes.ravel()

    for ax, item in zip(axes, STOCKS):
        closes = item["close"]
        color = UP if item["change_pct"] >= 0 else DOWN
        ax.plot(DATES, closes, color=color, linewidth=2.8, marker="o", markersize=6)
        ax.fill_between(DATES, closes, min(closes), color=color, alpha=0.08)

        ax.set_title(f"{item['name']} ({item['ticker']})", fontsize=14, fontweight="bold", color=TEXT, pad=10)
        ax.text(
            0.02,
            0.88,
            f"최근 종가 {format_krw(closes[-1])}  |  {item['change_pct']:+.2f}%",
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

    fig.suptitle("종목별 최근 4거래일 종가 흐름", fontsize=19, fontweight="bold", color=TEXT, y=0.99)
    fig.text(0.99, 0.01, "기준 기간: 2026-05-28 ~ 2026-06-02", ha="right", fontsize=10, color=MUTED)

    out = OUT_DIR / "daily_briefing_price_trends_2026-06-03.png"
    fig.tight_layout(rect=[0, 0.03, 1, 0.95])
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


if __name__ == "__main__":
    setup_font()
    print(save_change_chart().resolve())
    print(save_price_trends().resolve())
