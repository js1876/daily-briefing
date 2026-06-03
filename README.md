# Daily Briefing

매일 오전 10시에 국내 반도체 포트폴리오 가격, 뉴스, 매크로 지표, 반도체 사이클 분석을 리서칭해 HTML 브리핑을 생성하고 GitHub Pages에 배포한 뒤 디스코드 웹훅으로 링크를 전달합니다.

## 구조

- `public/`: 웹호스팅용 정적 파일 루트
- `public/index.html`: 웹호스팅 기본 진입 파일
- `public/latest.html`: 최신 브리핑 HTML
- `public/latest_bundle.html`: 디스코드 첨부용 단일 HTML
- `public/assets/charts/`: 최신/날짜별 차트 PNG
- `public/archive/reports/`: GitHub Pages에서 접근 가능한 날짜별 브리핑 HTML
- `archive/reports/`: 날짜별 브리핑 HTML 아카이브
- `archive/markdown/`: 과거 마크다운 브리핑 아카이브
- `scripts/generate_daily_briefing.py`: 자동 리서칭/생성/전송 메인 스크립트
- `scripts/send_discord_notification.py`: GitHub Pages 확인 후 디스코드 링크 전송
- `scripts/legacy/`: 초기 수동 생성용 보조 스크립트 보관
- `config/discord_webhook_url.txt`: 디스코드 웹훅 URL 설정
- `logs/`: 자동 실행 및 테스트 로그

## 실행

- 정기 실행: `run_daily_briefing.bat`
- 수동 전송 테스트: `test_discord_briefing_send.bat`

Windows 작업 스케줄러 작업명은 `CodexDailySemiconductorBriefing`입니다.

## Daily Flow

1. 오전 10시에 리서칭을 실행합니다.
2. 얻은 데이터로 `public/index.html`과 관련 차트를 갱신합니다.
3. 변경분을 GitHub 저장소에 commit/push합니다.
4. GitHub Pages 공개 URL이 정상 응답하는지 확인합니다.
5. 디스코드에 사용자 멘션, 핵심 요약, 종목별 가격정보, 웹페이지 링크를 전송합니다.

## GitHub Pages

GitHub 저장소 Pages 설정에서 publishing source를 `main` 브랜치의 `/public` 폴더로 지정합니다.

웹 루트:

- `public/index.html`

매일 실행 후 `run_daily_briefing.bat`가 변경된 `public/`, `archive/`, 스크립트를 커밋하고 push합니다. 이후 `https://js1876.github.io/daily-briefing/public/` 확인이 끝나면 디스코드 메시지를 보냅니다.
