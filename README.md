# 층위(層位) — 서울 오피스의 공간·자본·시간

[![CI](https://github.com/yooooonjae/cheungwi/actions/workflows/ci.yml/badge.svg)](https://github.com/yooooonjae/cheungwi/actions/workflows/ci.yml)
[**cheungwi.pages.dev**](https://cheungwi.pages.dev)

서울 3대 권역(CBD·GBD·YBD) 프라임 오피스 55동을 공공 원천에서 수집해, 유효임대료에서
NOI·자산가치·Equity IRR·차환 가능성까지 한 줄기로 잇는 개인 연구 포트폴리오다.
**임대의 층이 쌓이고, 부채의 물이 차오른다** — 서장의 한 줄이 이 저장소의 주제다.

## 시리즈 계보

네 저장소는 같은 자산을 서로 다른 축에서 본다. 앞의 셋이 만든 규약(단일 HTML 셸·데이터 원장·
패리티 검사)을 그대로 물려받고, 층위는 거기에 **시간축**을 얹었다.

| 저장소 | 축 | 보는 것 |
|---|---|---|
| 수지(收支) · [yoonjae.pages.dev](https://yoonjae.pages.dev) | 사업 | 개발 사업의 수지 — 짓는 값과 파는 값 |
| 순환(循環) · [sunhwan.pages.dev](https://sunhwan.pages.dev) | 주기 | 공급→분양→운영→자본의 한 바퀴 |
| 시차(視差·時差) · [sicha.pages.dev](https://sicha.pages.dev) | 관측 | 같은 값을 보는 각도차와 전달 시차 |
| **층위(層位)** · [cheungwi.pages.dev](https://cheungwi.pages.dev) | 단면 | 공간·자본·시간이 한 기둥에 쌓인 단면 |

## 시작하기

```bash
make setup && make test     # venv 생성·의존성 설치 후 테스트
cp config.example.json config.json   # 그리고 각 키 값을 채운다
make collect                # 수집기 5종 실행 (재개형)
make manifest               # 수집 산출을 훑어 데이터 원장 갱신
make analyze                # 엔진을 실데이터에 적용해 out/*.json 4종 생성
make build                  # site/ 소스를 web/ 정적 산출로 굽는다
make serve                  # web/ 을 로컬에서 본다 (기본 8768)
make refresh                # 위 전부 + 검증 + 배포를 한 번에 (매일 도는 것은 이것뿐이다)
```

| 타깃 | 하는 일 |
|---|---|
| `make setup` | venv 생성 + 의존성 설치(pytest 하나) |
| `make collect` | 수집기 5종 실행(재개형 — 쿼터가 끊기면 다음 실행이 이어받는다) |
| `make manifest` | 수집 산출을 훑어 `data/DATA_MANIFEST.json` 갱신 |
| `make analyze` | 엔진을 실데이터에 적용해 `out/*.json` 4종 생성(멱등·원자적) |
| `make build` | `site/` → `web/` 정적 산출(원자적 — 실패하면 기존 `web/` 그대로) |
| `make serve` | `web/` 로컬 서빙(기본 8768 · 봇 차단·noindex) |
| `make test` | pytest 전체 |
| `make check` | **CI 동등 검증** — 바이트컴파일·스크립트 문법·전체 스위트·빌드 게이트 |
| `make responsive` | 다섯 뷰포트 실측 + 다크 스크린샷(헤드리스 크롬) |
| `make og` | OG 카드 재생성(`src/build/og_card.html` → `site/static/og.png` 1200×630) |
| `make refresh` | 수집→분석→원장→빌드→검증→배포. **매일 도는 것은 이것뿐이다** |
| `make dryrun` | 수집·배포 없이 뒷단만(분석→원장→빌드→검증) |

## 아키텍처

```
data/raw/{source}/     API 원본 응답 캐시(재실행을 증분화한다)
   │  src/collect/     수집기 5종 — 표준 라이브러리만, 재개형, 마지막 줄이 마커
   ▼
data/*.json            원천별 산출 + DATA_MANIFEST.json(관측월·수집일·coverage·cache)
   │  src/analysis/    순수 함수 8모듈(파일·네트워크를 건드리지 않는다)
   │  └ build_out.py   ← 순수 함수를 실데이터에 붙이는 유일한 자리
   ▼
out/*.json             market · underwriting · trades_analysis · pf_case
   │  src/build/       assemble.py — 템플릿 치환 → 두 게이트 → 원자 스왑
   ▼
web/                   index.html + css/ + js/ + data/*.js (외부 요청 0)
   │  src/pipeline/    refresh.py — 무효화→수집→분석→원장→빌드→검증→배포
   ▼
cheungwi.pages.dev
```

엔진은 두 벌이다. 파이썬(`src/analysis/`)이 산출을 만들고, 자바스크립트 미러
(`site/js/engine.js`)가 실험실의 손잡이를 화면에서 다시 계산한다. 둘이 갈라지면 화면과 산출이
다른 말을 하므로, 패리티 검사가 200조 이상의 표본으로 값과 **오류 갈래**까지 맞춘다
(`tests/test_parity.py` · node 프로세스를 실제로 왕복시킨다).

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

## 분석 산출

`src/analysis/`의 여덟 모듈(금융코어·유효임대료·NOI·cap rate·가치·인수금융·차환·개발 PF)은 파일도
네트워크도 건드리지 않는 순수 함수이고, 그것을 실데이터에 붙이는 자리는 `build_out.py`
하나뿐이다. `make analyze`가 네 산출을 만든다.

| 산출 | 담는 것 |
|---|---|
| `out/market.json` | 권역 3종의 유효임대료·공실률·cap 벤치마크·금리 3계열·스프레드(cap − 국고채10년) |
| `out/underwriting.json` | 시드 55동의 언더라이팅. 건축물대장이 없는 동은 `pending_ledger` |
| `out/trades_analysis.json` | 해제 거래를 뺀 실거래의 권역별·연도별 중위 평당가와 매칭 사다리 |
| `out/pf_case.json` | 대표 가상 사업지의 월별 인출·이자 스케줄과 스트레스 15행 |

같은 입력이면 같은 바이트가 나온다(벽시계 시각을 싣지 않는다). 조립을 모두 끝낸 뒤에
쓰고 쓰기는 임시 파일 → rename이라, 도중에 실패하면 기존 `out/`이 그대로 남는다.

**대장이 없다는 사실을 메우지 않는다.** 건축물대장 활용신청이 승인되기 전이라 지금은
55동 전부가 `pending_ledger`이고, 그 동들은 연면적을 몰라 NOI 이하를 계산하지 않는다 —
빈 자리를 권역 평균으로 칠하면 추정과 부재가 같은 색이 된다. 승인 뒤 재수집·재실행하면
그대로 승격된다. 물리 게이트(cap 0.02~0.12 · 유효임대료 10,000~60,000원/㎡·월 · DSCR 0~5)에
걸린 값은 조용히 빠지지 않고 `gate_violations`·`errors`에 사유와 함께 남는다.

## 데이터 원장

`make manifest`가 여섯 산출을 훑어 `data/DATA_MANIFEST.json`을 만든다. 원천마다 **관측월**
(`observed_through`, 데이터가 실제로 보는 마지막 시점)과 **수집일**(`collected_at`, API를 부른
날)을 나눠 적는다. 같은 날 받아도 R-ONE 임대동향은 분기 지표라 2026Q1까지, 금리는 2026-06까지,
실거래는 당일까지 관측한다 — 이 간격이 곧 데이터 지연이고, 뭉뚱그리지 않는 것이 원장의 목적이다.

`data_cutoff`는 **자기 시점축을 가진** 원천(실거래·임대동향·리츠·금리, 원장의 `time_axis`)의
관측월 중 완결된 달의 최신 월이다. 완결 판정선은 오늘과 수집일 중 이른 달이라, 다시 받지 않고
달만 넘겨도 기준월은 제자리에 있는다. 시드와 건물 마스터는 관측월이 수집일에서 나오는
스냅샷이라 후보에서 뺀다. `coverage`에는 규모와 함께 빠진 부분을 적고(예: 건축물대장은
활용신청 승인 전이라 `대장 0/55`), `cache`에는 재실행이 캐시를 어디까지 믿는지를 적는다 —
수집기마다 정책이 달라서(R-ONE은 무효화 없는 캐시 우선, 금리는 매번 재호출, 실거래는
캐시 우선에 진행 파일) 원장을 보지 않으면 어느 값이 언제 갱신되는지 알 수 없다.

## 자동 갱신과 배포

`src/pipeline/refresh.py` 하나가 **무효화 → 수집 → 분석 → 원장 → 빌드 → 검증 → 스위트 → 배포**를
잇는다.
launchd 가 매일 09:10 에 이것을 부르고(`docs/launchd-setup.md`), 결과는
`https://cheungwi.pages.dev` 에 올라간다.

```bash
make refresh                              # 전체
make dryrun                               # 수집·배포 없이 뒷단만 (분석→원장→빌드→검증)
make refresh ARGS="--only trades"         # 한 수집기 + 이후 단계 전부
```

**소스별로 독립해서 실패한다.** `make collect` 은 `|| exit 1` 로 묶여 있어 한 수집기가 죽으면
뒤가 통째로 멈추지만, 파이프라인에서는 다섯이 각자 돈다 — 실패한 소스는 직전 `data/*.json`
이 그대로 남아 사이트는 옛 데이터로 빌드되고, 그 사실이 `logs/refresh-status.json` 에
남는다(조용한 최신 위장을 하지 않는다). 반대로 **분석이 실패하면 `out/` 을 실행 전 상태로
되돌리고 빌드로 넘어가지 않는다** — 넷 중 둘만 새것인 혼재를 화면에 올리느니 직전 사이트를
그대로 두는 쪽이 낫다. 실패가 하나라도 있으면 배포하지 않는다(pages.dev 는 직전 배포를
계속 서빙한다).

**배포 직전에 계약 스위트가 한 번 더 돈다**(`CHEUNGWI_REQUIRE_ARTIFACTS=1`). 검증 단계가 보는
것은 index 가 있는가·오늘 구웠는가·JSON 이 파싱되는가까지고, 그 셋은 "파일이 생겼다"는 증거지
"값이 말이 된다"는 증거가 아니다. 새 분기 데이터가 단위·게이트·사다리 항등식·패리티를 깼는지는
스위트만 안다. 깨지면 그 자리에서 멈추고 배포하지 않는다.

**상태 파일은 일하기 전에 먼저 쓴다**(`state: running`·`ok: false`). 파이프라인이 예외로
즉사한 날에도 `logs/refresh-status.json` 이 전날의 `ok: true` 로 남아 있으면, 그 파일을 보라고
적어 둔 확인 절차가 어제의 성공을 오늘의 성공으로 읽는다. 예외는 `failures` 와 `traceback`
으로 환원되고 `state` 는 `crashed` 가 된다.

수집기 stdout 의 마지막 줄 `COMPLETE`/`RESUME_NEEDED` 가 마커다. `RESUME_NEEDED` 는 실패가
아니라 다음 실행이 이어받는다는 뜻이고, 건축물대장이 잠겨 있는 지금 `buildings` 는 늘 이쪽이다.

**캐시를 어디까지 믿을지가 원천마다 다르므로 무효화도 원천마다 다르다.**

| 원천 | 매 실행 |
|---|---|
| 실거래 | 최근 3개월 셀의 원문 캐시를 지우고 진행 파일·`meta.cells_done` 을 같은 수만큼 낮춘다 — 뒤늦은 신고가 계속 붙는 달이라서다. 셋을 함께 낮추지 않으면 `save_result` 의 축소 방어가 재수집분을 `.partial` 로 밀어낸다 |
| R-ONE | `--refresh-latest` 로 각 계열의 **최신 기간표 캐시만** 삭제(새 분기는 거기에만 붙는다. 통째로 지우면 13년치를 매일 다시 받는다) |
| 리츠 | corpCode zip 은 하루 한 번만 받는다(수 MB 전체 재다운로드가 DART 쿼터를 태운다) |
| 금리 | 원래 매 실행 재호출한다(월 시계열이라 최신 월이 계속 는다) |
| 건물 | 대장 XML·VWorld 캐시는 그대로 둔다(승인 전이라 받을 것이 없다) |

## 검사

`make check` 가 넷을 돈다 — 파이썬 전 소스 바이트컴파일, 사이트 스크립트 문법
(`node --check` 를 **파일마다**: 다중 인자를 주면 첫 파일만 본다), pytest 전체, 그리고 빌드
게이트(미치환 플레이스홀더·한국어 조사 분리·선언과 실재의 불일치). GitHub Actions 는 push·PR
마다 **바로 이 명령을 부른다**(`.github/workflows/ci.yml` 의 마지막 스텝이 `make check` 다).
스텝을 따로 나열하면 로컬과 CI 가 조용히 갈라지므로, 무엇이 도는지의 단일 출처는 Makefile 이다.

**CI 는 배포하지 않는다.** 배포는 로컬 `refresh` 만 한다 — 초록 체크가 곧 배포가 되면
"검증된 것만 나간다"는 순서가 뒤집힌다. 수집기도 부르지 않는다(키가 없고, 쿼터를 태울 이유도
없다). 대신 `refresh` 가 빌드 뒤 배포 전에 같은 스위트를 한 번 더 돌린다 — CI 가 검사하는 것은
**커밋된** 산출이고 배포되는 것은 **방금 구운** 산출이라, 그 한 번이 없으면 검사받은 것과
나가는 것이 갈린다.

**커밋된 산출물이 낡지 않았는지도 검사한다.** 산출물을 커밋해 두는 계약(아래)은 `src/analysis`
를 고치고 `make analyze` 를 잊는 순간 배신당한다 — 그 커밋에서 CI 가 증명하는 것은 "지금 코드가
옳다"가 아니라 "낡은 산출물끼리 아귀가 맞는다"이다. 그래서 스위트가 커밋된 `data/` 로 넷을 다시
구워 커밋본과 sha256 을 맞대 본다(1초 미만).

**산출물 부재는 skip 이 아니라 실패다.** 이 스위트의 상당수는 `out/`·원장의 실물을 읽어
검증하므로, 산출물이 없는 러너에서 순수 함수 검사만 통과한 초록은 "검사했다"가 아니라
"검사하지 않았다"는 뜻이 된다. 그래서 산출물 4종·원장·OG 카드는 저장소에 커밋해 두고
(checkout 만으로 실측이 된다), CI 는 `CHEUNGWI_REQUIRE_ARTIFACTS=1` 로 가드를 켠다 — 하나라도
없으면 세션은 첫 검사 전에 부재 목록을 들고 멈춘다(`conftest.py`).

`make responsive` 는 크롬을 띄우므로 `make check` 에 묶지 않았다(헤드리스 잡은 직렬로
세워야 한다). 릴리스 전에 따로 돌린다.

## OG 카드

`src/build/og_card.html` 이 카드의 원본이다 — 서장의 도면을 그대로 줄인 미니어처(20층 × 6칸의
창 중 여덟이 꺼져 있고, 자본 스택을 부채의 수면이 절반 높이에서 가로지른다)에 「층위 層位」와
한 줄이 붙는다. 색은 `tokens.css` 의 야간 값을 그대로 옮겨 적었고, 외부 자원은 하나도 부르지
않는다(`file://` 로 찍히므로 네트워크 자원은 빈칸이 된다).

```bash
make og      # 크롬 헤드리스로 1200×630 을 굽고 크기를 검증한다 → site/static/og.png
```

굽고 나면 **커밋한다**. 빌드가 `site/static/` 을 `web/` 루트로 평면 복사하고, `index` 의
`og:image` 가 그 자리를 절대 URL 로 가리킨다 — 메타는 있는데 파일이 없는 404 미리보기를
막으려고, 검사가 메타가 가리키는 경로에 실제 파일이 있는지까지 본다.
