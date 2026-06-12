import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "direct_channel_report.py"
spec = importlib.util.spec_from_file_location("direct_channel_report", MODULE_PATH)
dcr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dcr)


def base_summary():
    return {
        "date": "2026-06-11",
        "site_url": "https://example.com/briefing/",
        "cycle_summary": "반도체 사이클 요약입니다.",
        "prices": [
            {"name": "삼성전자", "close": 1000, "change": 10, "change_pct": 1.0},
            {"name": "SK하이닉스", "close": 2000, "change": -20, "change_pct": -1.0},
        ],
        "macro": {},
    }


def test_weather_message_is_added_when_weather_exists():
    summary = base_summary()
    summary["weather"] = {
        "location": "서울",
        "condition": "맑음",
        "current_temp": 24,
        "high_temp": 29,
        "low_temp": 19,
        "pm10": 32,
        "precipitation": None,
    }

    message = dcr.build_message(summary)

    assert "오늘 서울 날씨는 맑음일 것으로 예상됩니다." in message
    assert "최고기온은 29도, 최저기온은 19도입니다." in message
    assert "현재 기온은 24도이고 미세먼지 지수는 32입니다." in message
    assert "우산" not in message


def test_weather_message_adds_umbrella_note_for_rain():
    summary = base_summary()
    summary["weather"] = {
        "location": "서울",
        "condition": "흐리고 비",
        "current_temp": 21,
        "high_temp": 25,
        "low_temp": 18,
        "pm10": 20,
        "precipitation": {"time": "15시", "type": "비"},
    }

    message = dcr.build_message(summary)

    assert "오늘 15시에 비가 예정되어 있습니다. 우산을 챙기시길 추천드립니다." in message


def test_weather_message_is_omitted_when_weather_missing():
    message = dcr.build_message(base_summary())

    assert "오늘 서울 날씨" not in message
    assert "미세먼지" not in message


def test_calendar_message_lists_today_events():
    summary = base_summary()
    summary["calendar_events"] = [
        {"summary": "치과", "time": "10:30"},
        {"summary": "저녁 약속", "time": None},
    ]

    message = dcr.build_message(summary)

    assert "오늘 일정은 10:30 치과, 저녁 약속이 있습니다." in message


def test_calendar_message_says_no_events_when_empty():
    summary = base_summary()
    summary["calendar_events"] = []

    message = dcr.build_message(summary)

    assert "오늘은 특별한 일정이 없습니다." in message


def test_all_day_event_ending_today_is_not_today_event():
    ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART;VALUE=DATE:20260611
DTEND;VALUE=DATE:20260612
SUMMARY:어제 종일 일정
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=Asia/Seoul:20260612T100000
DTEND;TZID=Asia/Seoul:20260612T110000
SUMMARY:오늘 일정
END:VEVENT
END:VCALENDAR
"""

    events = dcr.parse_ics_events(ics, target_date=dcr.datetime(2026, 6, 12, tzinfo=dcr.KST).date())

    assert events == [{"summary": "오늘 일정", "time": "10:00", "sort": "2026-06-12T10:00:00+09:00"}]
