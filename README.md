# 층위(層位) — 서울 오피스의 공간·자본·시간

서울 3대 권역(CBD·GBD·YBD) 프라임 오피스 50동을 공공 원천에서 수집해, 유효임대료에서
NOI·자산가치·Equity IRR·차환 가능성까지 한 줄기로 잇는 개인 연구 포트폴리오다.

시리즈 계보: 수지(收支) → 순환(循環) → 시차(視差·時差) → **층위(層位)**.

## 시작하기

```bash
make setup && make test     # venv 생성·의존성 설치 후 테스트
cp config.example.json config.json   # 그리고 각 키 값을 채운다
make collect                # 수집기 5종 실행 (재개형)
```

수집기는 파이썬 표준 라이브러리만 쓴다(pytest는 테스트 전용). 저장 형식은 JSON 단일이고,
API 원본 응답은 `data/raw/{source}/`에 전량 캐시해 재실행을 증분화한다. 실거래 캐시
(`data/raw/trades/`)만은 서울 5개 구 × 2006년 이후 1,200여 개 파일이라 저장소에 담지 않는다 —
`python3 src/collect/trades.py`를 다시 돌리면 중단 지점부터 이어서 받는다.

## 데이터 출처

| 기관 | 데이터셋 | 산출 |
|---|---|---|
| 국토교통부 건축HUB | 건축물대장 표제부 | `data/buildings.json` |
| 국토교통부 RTMS | 상업업무용 실거래 | `data/trades.json` |
| 한국부동산원 R-ONE | 상업용(오피스) 임대동향 | `data/rone_office.json` |
| 금융감독원 DART | 오피스 보유 상장리츠 재무·배당 | `data/reits.json` |
| 한국은행 ECOS | 국고채 10년·CD 91일·기업대출 금리 | `data/rates.json` |
| 국토교통부 VWorld | 좌표·용도지역·공시지가 | (buildings에 병합) |
