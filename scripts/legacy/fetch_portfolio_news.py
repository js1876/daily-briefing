import html
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo


DOMESTIC_QUERIES = [
    ("TIGER 반도체TOP10", "TIGER 반도체TOP10 396500"),
    ("KODEX 200타겟위클리커버드콜", "KODEX 200타겟위클리커버드콜 498400"),
    ("삼성전자", "삼성전자 005930"),
    ("SK하이닉스", "SK하이닉스 000660"),
]


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


def fetch_domestic_news():
    kst = ZoneInfo("Asia/Seoul")
    today = datetime.now(kst).date()
    print(f"TODAY_KST\t{today}")

    for stock_name, query in DOMESTIC_QUERIES:
        url = google_news_rss(query)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=20).read()
        root = ET.fromstring(raw)

        print(f"###\t{stock_name}\t{url}")
        count = 0
        for item in root.findall("./channel/item"):
            title = html.unescape((item.findtext("title") or "").strip())
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            source_el = item.find("source")
            source = html.unescape((source_el.text or "").strip()) if source_el is not None else ""

            try:
                published_kst = parsedate_to_datetime(pub_date).astimezone(kst)
            except (TypeError, ValueError):
                continue

            if published_kst.date() != today:
                continue

            print(f"{published_kst.isoformat()}\t{source}\t{title}\t{link}")
            count += 1
            if count >= 3:
                break
        print(f"COUNT\t{count}")


if __name__ == "__main__":
    fetch_domestic_news()
