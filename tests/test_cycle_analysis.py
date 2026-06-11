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
