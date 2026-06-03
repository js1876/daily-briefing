from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager


FONT_PATH = "C:/Windows/Fonts/malgun.ttf"
OUT = Path("daily_briefing_semiconductor_cycle_2026-06-03.png")


def setup_font() -> None:
    font_manager.fontManager.addfont(FONT_PATH)
    font_name = font_manager.FontProperties(fname=FONT_PATH).get_name()
    plt.rcParams["font.family"] = font_name
    plt.rcParams["axes.unicode_minus"] = False


def add_phase(ax, x, y, title, subtitle, color, align="center", title_offset=0.28, subtitle_offset=0.15):
    ax.scatter([x], [y], s=95, color=color, edgecolor="white", linewidth=2.5, zorder=5)
    ax.text(
        x,
        y + title_offset,
        title,
        ha=align,
        va="bottom",
        fontsize=13,
        fontweight="bold",
        color=color,
    )
    ax.text(
        x,
        y + subtitle_offset,
        subtitle,
        ha=align,
        va="bottom",
        fontsize=10.5,
        color="#475467",
    )


def main() -> None:
    setup_font()

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

    # Area bands make the phase easier to read than a bare line.
    ax.axhspan(0.55, 1.18, color="#fef2f2", alpha=0.9, zorder=0)
    ax.axhspan(-0.18, 0.55, color="#fffbeb", alpha=0.9, zorder=0)
    ax.axhspan(-1.18, -0.18, color="#eff6ff", alpha=0.9, zorder=0)
    ax.axhline(0, color="#98a2b3", linewidth=1.2)
    ax.plot(x, y, color="#1f2937", linewidth=3.0, zorder=2)
    ax.fill_between(x, y, 0, where=y >= 0, color=red, alpha=0.12, interpolate=True)
    ax.fill_between(x, y, 0, where=y < 0, color=blue, alpha=0.12, interpolate=True)

    # Current location: late expansion, before the theoretical peak.
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

    # Phase markers on the curve.
    phases = [
        (0.10 * np.pi, "회복 초입", "감산·재고 감소", green),
        (0.28 * np.pi, "가격 상승", "DRAM/NAND/HBM ASP 상승", amber),
        (0.50 * np.pi, "실적 피크 구간", "영업이익 폭증", red),
        (0.76 * np.pi, "CAPEX 증가", "공급 확대 준비", purple),
        (1.00 * np.pi, "피크아웃 경계", "주가 선반영·수급 둔화", red),
        (1.32 * np.pi, "가격 하락", "공급 과잉·재고 증가", blue),
        (1.50 * np.pi, "불황 저점", "적자·감산", blue),
        (1.78 * np.pi, "다음 회복 준비", "재고 소진·투자 축소", green),
    ]
    for px, title, subtitle, color in phases:
        py = np.sin(px)
        if title == "CAPEX 증가":
            add_phase(ax, px, py, title, subtitle, color, title_offset=-0.28, subtitle_offset=-0.42)
        else:
            add_phase(ax, px, py, title, subtitle, color)

    ax.text(
        np.pi / 2,
        1.29,
        "호황",
        ha="center",
        va="center",
        fontsize=18,
        fontweight="bold",
        color=red,
    )
    ax.text(
        3 * np.pi / 2,
        -1.29,
        "불황",
        ha="center",
        va="center",
        fontsize=18,
        fontweight="bold",
        color=blue,
    )
    ax.text(
        0.03,
        0.02,
        "저점",
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=12,
        color=muted,
    )
    ax.text(
        0.97,
        0.02,
        "다음 사이클",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=12,
        color=muted,
    )

    evidence = [
        ("가격", "TrendForce: 2Q26 DRAM +58~63%, NAND +70~75% QoQ 전망"),
        ("실적", "삼성 DS OP: 1Q25 1.1조원 → 1Q26 53.7조원"),
        ("밸류", "forward PER 6배대: 호황기 저PER 착시 가능"),
        ("수급", "KOSPI 고점권, 외국인 매도 지속, 차익실현 압력"),
        ("CAPEX", "SK하이닉스 생산능력 확대 계획: 미래 공급 리스크"),
    ]
    panel_x = 4.15
    panel_y = 0.78
    ax.text(panel_x, panel_y, "판단 근거", fontsize=17, fontweight="bold", color=text, ha="left")
    for idx, (label, desc) in enumerate(evidence):
        yy = panel_y - 0.16 - idx * 0.14
        ax.text(
            panel_x,
            yy,
            label,
            fontsize=10.5,
            fontweight="bold",
            color="white",
            ha="center",
            va="center",
            bbox={"boxstyle": "round,pad=0.35", "facecolor": "#111827", "edgecolor": "#111827"},
        )
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
    fig.savefig(OUT, bbox_inches="tight", facecolor="white")
    print(OUT.resolve())


if __name__ == "__main__":
    main()
