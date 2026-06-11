#!/usr/bin/env python3
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_FILE = ROOT / "logs" / "latest_summary.json"
MENTION_USER_ID = "750311358855381087"
SEOUL_LAT = 37.5665
SEOUL_LON = 126.9780
WEATHER_CODE_LABELS = {
    0: "맑음",
    1: "대체로 맑음",
    2: "구름 조금",
    3: "흐림",
    45: "안개",
    48: "안개",
    51: "이슬비",
    53: "이슬비",
    55: "이슬비",
    61: "비",
    63: "비",
    65: "강한 비",
    71: "눈",
    73: "눈",
    75: "강한 눈",
    80: "소나기",
    81: "소나기",
    82: "강한 소나기",
    85: "눈 소나기",
    86: "눈 소나기",
    95: "천둥번개",
    96: "천둥번개와 우박",
    99: "천둥번개와 우박",
}


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


def round_temp(value) -> int:
    return int(round(float(value)))


def precipitation_type(weather_code: int) -> str | None:
    if weather_code in {71, 73, 75, 77, 85, 86}:
        return "눈"
    if weather_code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}:
        return "비"
    return None


def first_precipitation(hourly: dict) -> dict | None:
    times = hourly.get("time", [])
    codes = hourly.get("weather_code", [])
    probabilities = hourly.get("precipitation_probability", [])
    for idx, time_text in enumerate(times[:24]):
        code = int(codes[idx]) if idx < len(codes) else 0
        probability = probabilities[idx] if idx < len(probabilities) else 0
        kind = precipitation_type(code)
        if kind and probability >= 30:
            hour = datetime.fromisoformat(time_text).hour
            return {"time": f"{hour:02d}시", "type": kind}
    return None


def get_json_with_retries(url: str, params: dict, attempts: int = 3) -> dict:
    full_url = f"{url}?{urllib.parse.urlencode(params)}"
    last_error = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(full_url, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(1 + attempt)
    raise RuntimeError(f"weather request failed: {last_error}")


def fetch_wttr_weather() -> dict | None:
    try:
        data = get_json_with_retries("https://wttr.in/Seoul", {"format": "j1", "lang": "ko"}, attempts=3)
        current = data["current_condition"][0]
        today = data["weather"][0]
        desc = current.get("lang_ko", current.get("weatherDesc", [{}]))[0].get("value", "변동성 있는 날씨")
        desc_lower = desc.lower()
        if "rain" in desc_lower or "비" in desc:
            condition = "비"
        elif "snow" in desc_lower or "눈" in desc:
            condition = "눈"
        elif "cloud" in desc_lower or "구름" in desc or "흐" in desc:
            condition = "흐림"
        elif "clear" in desc_lower or "sun" in desc_lower or "맑" in desc:
            condition = "맑음"
        else:
            condition = desc

        precipitation = None
        for hourly in today.get("hourly", []):
            chance_rain = int(hourly.get("chanceofrain", 0) or 0)
            chance_snow = int(hourly.get("chanceofsnow", 0) or 0)
            if chance_rain >= 30 or chance_snow >= 30:
                hour = int(hourly.get("time", "0") or 0) // 100
                precipitation = {"time": f"{hour:02d}시", "type": "눈" if chance_snow > chance_rain else "비"}
                break

        return {
            "location": "서울",
            "condition": condition,
            "current_temp": round_temp(current["temp_C"]),
            "high_temp": round_temp(today["maxtempC"]),
            "low_temp": round_temp(today["mintempC"]),
            "pm10": None,
            "precipitation": precipitation,
        }
    except Exception:
        return None


def fetch_seoul_weather() -> dict | None:
    try:
        forecast_data = get_json_with_retries(
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": SEOUL_LAT,
                "longitude": SEOUL_LON,
                "timezone": "Asia/Seoul",
                "current": "temperature_2m,weather_code",
                "hourly": "weather_code,precipitation_probability",
                "daily": "temperature_2m_max,temperature_2m_min",
                "forecast_days": 1,
            },
        )

        pm10 = None
        try:
            air_data = get_json_with_retries(
                "https://air-quality-api.open-meteo.com/v1/air-quality",
                {
                    "latitude": SEOUL_LAT,
                    "longitude": SEOUL_LON,
                    "timezone": "Asia/Seoul",
                    "current": "pm10",
                },
            )
            pm10 = air_data.get("current", {}).get("pm10")
        except Exception:
            pm10 = None

        current = forecast_data.get("current", {})
        daily = forecast_data.get("daily", {})
        weather_code = int(current.get("weather_code", 3))
        return {
            "location": "서울",
            "condition": WEATHER_CODE_LABELS.get(weather_code, "변동성 있는 날씨"),
            "current_temp": round_temp(current["temperature_2m"]),
            "high_temp": round_temp(daily["temperature_2m_max"][0]),
            "low_temp": round_temp(daily["temperature_2m_min"][0]),
            "pm10": int(round(float(pm10))) if pm10 is not None else None,
            "precipitation": first_precipitation(forecast_data.get("hourly", {})),
        }
    except Exception:
        return fetch_wttr_weather()
def weather_message(weather: dict | None) -> str:
    if not weather:
        return ""
    pm10 = weather.get("pm10")
    current_line = f"현재 기온은 {weather['current_temp']}도입니다."
    if pm10 is not None:
        current_line = f"현재 기온은 {weather['current_temp']}도이고 미세먼지 지수는 {pm10}입니다."
    lines = [
        f"오늘 {weather.get('location', '서울')} 날씨는 {weather['condition']}일 것으로 예상됩니다.",
        f"최고기온은 {weather['high_temp']}도, 최저기온은 {weather['low_temp']}도입니다.",
        current_line,
    ]
    precipitation = weather.get("precipitation")
    if precipitation:
        lines.append(f"오늘 {precipitation['time']}에 {precipitation['type']}가 예정되어 있습니다. 우산을 챙기시길 추천드립니다.")
    elif "비" in str(weather.get("condition", "")) or "눈" in str(weather.get("condition", "")):
        lines.append(f"오늘 {weather['condition']} 가능성이 있습니다. 우산을 챙기시길 추천드립니다.")
    return "\n".join(lines)


def build_message(summary: dict) -> str:
    prices = summary["prices"]
    macro = summary.get("macro", {})
    date = summary["date"]
    site_url = summary["site_url"]
    up_count = sum(1 for row in prices if row["change_pct"] >= 0)
    down_count = len(prices) - up_count
    max_up = max(prices, key=lambda row: row["change_pct"])
    max_down = min(prices, key=lambda row: row["change_pct"])

    fx = macro.get("원/달러", {})
    tnx = macro.get("미국 10년물", {})
    oil = macro.get("WTI", {})

    price_lines = "\n".join(
        f"- {row['name']}: {money_krw(row['close'])} ({signed_money(row['change'])}, {signed_pct(row['change_pct'])})"
        for row in prices
    )
    weather_lines = weather_message(summary.get("weather"))
    weather_block = f"\n\n오늘의 날씨\n{weather_lines}" if weather_lines else ""

    return (
        f"<@{MENTION_USER_ID}> {date} 오늘의 브리핑 전달드립니다\n\n"
        f"핵심 요약\n"
        f"- {summary['cycle_summary']}\n"
        f"- 상승 {up_count}개 / 하락 {down_count}개, 최대 상승은 {max_up['name']} {signed_pct(max_up['change_pct'])}, 최대 하락은 {max_down['name']} {signed_pct(max_down['change_pct'])}입니다.\n"
        f"- 매크로: 원/달러 {metric_text(fx.get('value'), '원')} ({metric_text_signed(fx.get('change_pct'), '%')}), 미국 10년물 {metric_text(tnx.get('value'), '%')}, WTI {metric_text(oil.get('value'), '달러')} ({metric_text_signed(oil.get('change_pct'), '%')}).\n\n"
        f"종목별 가격정보\n"
        f"{price_lines}"
        f"{weather_block}\n\n"
        f"세부정보는 아래 링크에서 확인하세요.\n"
        f"{site_url}"
    )


def main() -> None:
    summary = load_summary()
    summary["weather"] = fetch_seoul_weather()
    message = build_message(summary)
    print(message)


if __name__ == "__main__":
    main()
