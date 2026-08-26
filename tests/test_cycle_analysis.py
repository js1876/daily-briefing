import importlib.util
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "generate_daily_briefing.py"
spec = importlib.util.spec_from_file_location("generate_daily_briefing", MODULE_PATH)
gdb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gdb)


def test_load_cycle_analysis_uses_matching_date(tmp_path):
    analysis_file = tmp_path / "cycle_analysis.json"
    analysis_file.write_text(
        '{"date":"2026-06-11","headline":"AI 분석 제목","summary_line":"AI 요약",'
        '"cycle_summary":"AI 사이클 요약","chart_caption":"AI 차트 캡션",'
        '"report_html":"<h3>AI 리포트</h3><p>프롬프트 기반 분석</p>"}',
        encoding="utf-8",
    )

    result = gdb.load_cycle_analysis(datetime(2026, 6, 11, tzinfo=ZoneInfo("Asia/Seoul")), analysis_file)

    assert result["headline"] == "AI 분석 제목"
    assert result["summary_line"] == "AI 요약"
    assert result["cycle_summary"] == "AI 사이클 요약"
    assert "프롬프트 기반 분석" in result["report_html"]


def test_load_cycle_analysis_ignores_stale_date(tmp_path):
    analysis_file = tmp_path / "cycle_analysis.json"
    analysis_file.write_text(
        '{"date":"2026-06-10","headline":"어제 분석","summary_line":"어제 요약"}',
        encoding="utf-8",
    )

    result = gdb.load_cycle_analysis(datetime(2026, 6, 11, tzinfo=ZoneInfo("Asia/Seoul")), analysis_file)

    assert result["headline"] == gdb.DEFAULT_CYCLE_ANALYSIS["headline"]
    assert result["summary_line"] == gdb.DEFAULT_CYCLE_ANALYSIS["summary_line"]


def test_sanitize_report_html_removes_script():
    html = gdb.sanitize_cycle_report_html('<h3>제목</h3><script>alert(1)</script><p onclick="x">본문</p>')

    assert "script" not in html.lower()
    assert "onclick" not in html.lower()
    assert "<h3>제목</h3>" in html
    assert "본문" in html


def test_safe_href_allows_only_http_urls():
    assert gdb.safe_href("https://example.com/news?a=1&b=2") == "https://example.com/news?a=1&amp;b=2"
    assert gdb.safe_href("http://example.com") == "http://example.com"
    assert gdb.safe_href("javascript:alert(1)") == "#"
    assert gdb.safe_href("data:text/html;base64,xxx") == "#"
    assert gdb.safe_href("//example.com/path") == "#"


def test_load_cycle_analysis_uses_market_based_action_items(tmp_path):
    analysis_file = tmp_path / "cycle_analysis.json"
    analysis_file.write_text(
        '{"date":"2026-06-11","action_items":["눌림 구간에서 분할 접근", "<script>bad()</script>금리 급등 시 비중 축소"]}',
        encoding="utf-8",
    )

    result = gdb.load_cycle_analysis(datetime(2026, 6, 11, tzinfo=ZoneInfo("Asia/Seoul")), analysis_file)

    assert result["action_items"] == ["눌림 구간에서 분할 접근", "금리 급등 시 비중 축소"]


def test_action_items_html_renders_market_based_actions():
    html = gdb.action_items_html(["외국인 순매수 전환 확인", "HBM 뉴스 후 추격매수 금지"])

    assert "<li>외국인 순매수 전환 확인</li>" in html
    assert "<li>HBM 뉴스 후 추격매수 금지</li>" in html


def sample_rendered_html():
    rows = [
        gdb.PriceRow(
            ticker="005930",
            name="삼성전자",
            close=1000,
            prev_close=900,
            change=100,
            change_pct=11.1,
            basis_date=datetime(2026, 6, 17, tzinfo=ZoneInfo("Asia/Seoul")),
            closes=[800, 850, 900, 1000],
            dates=["6/14", "6/15", "6/16", "6/17"],
        ),
        gdb.PriceRow(
            ticker="000660",
            name="SK하이닉스",
            close=2400,
            prev_close=2500,
            change=-100,
            change_pct=-4.0,
            basis_date=datetime(2026, 6, 17, tzinfo=ZoneInfo("Asia/Seoul")),
            closes=[2300, 2450, 2500, 2400],
            dates=["6/14", "6/15", "6/16", "6/17"],
        ),
    ]
    cycle_analysis = {
        **gdb.DEFAULT_CYCLE_ANALYSIS,
        "report_html": "<table><tr><th>구분</th><th>내용</th></tr><tr><td>긴 항목</td><td>메모리 회복, HBM 추격, NAND, 파운드리 같은 긴 문장</td></tr></table>",
        "action_items": ["장 초반 수급 확인", "환율과 금리 체크"],
    }
    return gdb.render_html(
        rows,
        news={"005930": [{"time": "09:10", "source": "테스트뉴스", "title": "HBM 뉴스", "link": "https://example.com"}]},
        macro={"원/달러": {"value": 1511.7, "change_pct": -0.2}, "미국 10년물": {"value": 4.4, "change_pct": 0.1}},
        valuation={},
        today=datetime(2026, 6, 17, tzinfo=ZoneInfo("Asia/Seoul")),
        chart_files={"change": "change.png", "trend": "trend.png", "cycle": "cycle.png"},
        cycle_analysis=cycle_analysis,
    )


def test_report_css_is_mobile_first_card_dashboard():
    css = gdb.css_from_existing()

    assert "overflow-x: hidden" in css
    assert "img, svg, canvas" in css
    assert ".stock-card" in css
    assert ".factor-card" in css
    assert ".news-timeline" in css
    assert "--radius-lg: 24px" in css
    assert 'html[data-theme="dark"]' in css
    assert "--surface-elevated" in css
    assert "--hero-panel" in css
    assert ".theme-toggle" in css
    assert ".dashboard-shell" in css
    assert ".side-column" in css
    assert "@container" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "img, svg, canvas, video" in css
    assert "color-scheme: dark" in css
    assert "IntersectionObserver" not in css
    assert "reveal-target" not in css
    assert "is-revealed" not in css
    assert "translate3d(0, 14px" not in css
    assert "skeleton-shimmer" in css
    assert "transition: all" not in css
    assert "--bg: #101114" in css
    assert "--surface-elevated: #1b1d23" in css
    assert "html[data-theme=\"dark\"] body" in css
    assert "position: sticky" not in css
    assert "max-height: calc(100vh" not in css
    assert "overflow: auto" not in css
    assert "min-width: 760px" not in css
    assert "overflow-x: auto" not in css


def test_rendered_html_uses_cards_instead_of_price_table():
    rendered = sample_rendered_html()

    assert "stock-card" in rendered
    assert "stock-grid" in rendered
    assert "factor-card" in rendered
    assert "news-timeline" in rendered
    assert "check-item" in rendered
    assert "<table" not in rendered
    assert "report-card" in rendered
    assert "오늘의 종목 카드" in rendered or "오늘의 종목 브리핑" in rendered
    assert "매크로 팩터" in rendered
    assert 'dashboard-shell' in rendered
    assert 'side-column' in rendered
    assert '<aside class="side-column"' in rendered
    assert '<details class="detail-pack cycle-detail"' in rendered
    assert 'company-detail' in rendered
    assert '상세 분석 카드 펼치기' in rendered
    assert 'data-theme-toggle' in rendered
    assert 'daily-briefing-theme' in rendered
    assert '다크모드' in rendered
    assert '라이트모드' in rendered
    assert '가격 확인:' in rendered
    assert '표시 가격: 조회 시점 최신가' in rendered
    assert '가격 기준:' not in rendered
    assert '가격 기준' not in rendered
    assert 'skeleton-screen' in rendered
    assert 'data-live-price="005930"' in rendered
    assert 'data-live-change="005930"' in rendered
    assert 'data-live-trend="005930"' in rendered
    assert 'data-live-feed="https://js1876.github.io/daily-briefing/public/market-live.json"' in rendered
    assert 'live-market.js' in rendered
    assert 'IntersectionObserver' in rendered  # count-up observer remains
    assert 'dataset.revealed' not in rendered
    assert 'reveal-target' not in rendered
    assert 'is-revealed' not in rendered
    assert 'motion-ready' not in rendered
    assert 'num-animate' in rendered
    assert 'dataset.counted' in rendered
    assert 'requestAnimationFrame' in rendered
    assert 'prefers-reduced-motion: reduce' in rendered
