# 토스증권 Open API 시장조회 연결

이 연동은 **시장 데이터 전용**이다. 계좌, 보유자산, 주문, 조건주문 endpoint를 호출하지 않는다.

## 1. 로컬 설정 입력

`config/toss_market.toml`의 두 placeholder만 토스 개발자 페이지에서 발급받은 값으로 교체한다.

- `client_id`: Client ID
- `client_secret`: Client Secret

이 파일은 `.gitignore` 처리돼 GitHub에 올라가지 않는다. Client Secret을 Discord, HTML, 로그에 붙이지 않는다.

## 2. 연결 확인

```bash
./run_toss_market_smoke.sh
```

성공하면 OAuth 토큰 발급 후 아래 공개 시장 데이터만 확인한다.

- 삼성전자 `005930`
- SK하이닉스 `000660`
- TIGER 반도체TOP10 `396500`
- 국내 장 운영 상태
- 각 종목 최근 일봉

## 3. 안전 경계

- 호출 허용: `/oauth2/token`, `/api/v1/prices`, `/api/v1/candles`, `/api/v1/market-indicators/*`, `/api/v1/exchange-rate`, `/api/v1/market-calendar/*`
- 호출 금지: `/api/v1/accounts`, `/api/v1/holdings`, `/api/v1/orders`, `/api/v1/conditional-orders`, `/api/v1/buying-power`, `/api/v1/sellable-quantity`, `/api/v1/commissions`

## 4. 다음 단계

스모크 테스트 성공 후 토스 데이터를 기존 브리핑의 국내 가격/일봉 수집 소스에 연결한다. API 오류·휴장·호출 제한이 발생하면 보고서 전체를 멈추지 않고, 가격 상태를 `조회 제한`으로 표시한다.
