# 계획 2(엔진)·계획 3(대시보드·파이프라인) 핸드오프

계획 1(데이터층, 2026-07-30 완료)이 다음 단계에 넘기는 계약과 설계 입력. 최종 전체 브랜치 리뷰의 트리아지 결과를 옮긴 것이다.

## 계획 2가 데이터를 읽을 때 지켜야 할 계약

- **거래-건물 매칭 과신 금지.** 필지까지 확정된 것은 `match_exact` 57행뿐이다. `match.building_id`가 채워진 734행은 "시드 55동 목록 안에서 후보가 유일"이라는 뜻일 뿐, 같은 법정동의 비-시드 건물과 구분되지 않는다. 모호 3,789행은 `building_id=null`+`candidates`다.
- **해제 거래는 보존돼 있다.** `canceled=true` 404행을 가격 분석 전에 반드시 필터하라(스펙 §4도 이 규약으로 정정됨).
- **리츠 revenue는 `holding`으로 구분해 쓰라.** `indirect`/`mixed` 리츠의 별도 영업수익(매출액)은 임대료가 아니라 배당·이자 성격이다. 유효임대료 앵커는 `direct`(코람코더원·삼성FN·한화) 우선.
- **건축물대장은 아직 비어 있다.** `buildings[].ledger`는 전부 null(활용신청 대기), trades의 `kind`는 전부 `jibun_only`. 승인 후 `docs/ledger-unlock-checklist.md` 절차를 먼저 밟은 뒤 소비하라.
- **단위.** `rone_office.rent_level`은 **천원/㎡**, `reits.total_div`는 **백만원**, 나머지 금액은 원. 원장(`DATA_MANIFEST.json`) 각 source의 `units` 키가 단일 출처다.
- **권역 매핑은 근사다.** `seed_buildings.meta.rone_region`(CBD→도심, GBD→강남, YBD→여의도마포)은 R-ONE 상권 경계와 1:1이 아니다 — 여의도마포는 마포 포함 합성 권역. 캘리브레이션에서 이 오차를 다뤄야 한다.
- `reits.fin[].basis`는 ISO(`YYYY-MM-DD`), 원문은 `basis_raw`. 리츠 결산월이 제각각이므로 시간축은 basis 기준.

## 계획 3(refresh·launchd·배포) 설계에 반드시 실을 것

- **캐시 무효화**: R-ONE(캐시 우선·무효화 없음 — 새 분기를 영원히 못 받는다)과 건축물대장 XML(동일)에 갱신 경로 필요. rates는 항상 재호출이라 무관.
- **trades 최근 월 재수집 규칙**: 현재 `complete=true`라 재실행이 아무것도 안 한다. launchd 등록 전에 최근 2~3개월 캐시 무효화 규칙 필요. 단 `save_result`의 축소 방어(`meta.cells_done` 비교)와 충돌하지 않게 설계할 것(`--force` 탈출구 부재).
- **소스별 독립 실패**: `make collect`의 `|| exit 1` 체인은 refresh.py에서 수지 패턴(개별 실패 기록 후 계속)으로 대체.
- **corp_code ZIP 캐시**: reits가 매 실행 corpCode.xml 전체를 재다운로드(DART 쿼터 소모).
- **launchd 환경**: LANG 미상속 — 인코딩은 코드에 명시돼 있지만(utf-8), PATH·환경변수 상속에 주의(기존 시리즈의 launchd 사고 전력).
- 마커 규약: 모든 수집기 stdout 마지막 줄 `COMPLETE`/`RESUME_NEEDED`. 재개 판단은 이 마커로.

## 계획 2 → 계획 3 인수인계 (엔진·`out/*.json` 을 읽는 쪽이 알아야 할 것)

계획 2(엔진, 2026-07-30 완료)가 넘기는 세 가지다. 셋 다 "지금 눈에 보이는 모양"과 "곧 바뀔 모양"이 달라서, 대시보드가 지금 데이터만 보고 짜면 대장 승격 순간에 깨진다.

### ① `underwriting.buildings[]` 행은 세 변종이다

모든 변종이 공유하는 키: `id` · `name` · `region_code` · `region` · `sgg_cd` · `umd` · `jibun` · `address_road` · `region_figures` · `land` · `ledger_flags` · `pending_ledger`.

| 변종 | 판별 | 더 붙는 키 | 없는 키 |
|---|---|---|---|
| **pending** (대장 부재) | `pending_ledger === true` | `pending_reason` · `blocked`(막힌 함수 이름 7개 배열) | `ledger` · `underwriting` |
| **승격** (계산 성공) | `pending_ledger === false` 이고 `underwriting` 있음 | `ledger`(대장 원본) · `underwriting`(보정→NOI→가치→대출→보유→차환 전체) | `pending_reason` · `blocked` · `underwriting_error` |
| **실패** (계산 중 예외) | `pending_ledger === false` 인데 `underwriting` 없음 | `ledger` · `underwriting_error`{`kind`, `reason`} | `underwriting` |

**지금은 55동 전부가 pending 이다.** 건축물대장 활용신청이 승인되어 `ledger` 가 채워지는 순간 대부분이 승격으로 바뀌고, 그때 행의 모양이 달라진다 — `row.underwriting.noi.noi_won_y` 를 무조건 짚는 코드는 지금은 55동 전부에서, 승격 뒤에는 실패 행에서 터진다. **`pending_ledger` 만 보고 갈라도 안 된다**(실패 행이 `false` 다). `underwriting` 키의 유무로 갈라라.

실패 행은 최상위 `errors[]` 에도 같은 내용(`id`·`name`·`kind`·`reason`)이 실린다. `kind` 는 `NotImplementedError`(계산 불가) · `RuntimeError`(물리 게이트 — 단위 의심) · `ValueError`(입력 오류) 셋 중 하나다.

### ② 반환 봉투 규약이 세 갈래다 (엔진 함수를 직접 부를 때)

가정·유보를 어디에 싣는지가 함수마다 다르다. 한 갈래로 가정하고 짜면 `caveats` 가 조용히 화면에서 사라진다.

| 갈래 | 함수 | 모양 |
|---|---|---|
| 리스트 + 최상위 `caveats` | `effective_rent.building_adjust` | `{value, factors, assumptions: [문장 배열], caveats: [...]}` — `assumptions` 가 **배열**이다 |
| 최상위 `caveats`, `assumptions` 없음 | `caprate.benchmark` | `{cap_income_based, quarters_used, caveats: [...]}` |
| `assumptions` **dict 안에 내장** | `noi.noi` · `acquisition.max_loan` · `acquisition.hold_model` · `refi.refi_test` · `pf.pf_model` | `{...수치, assumptions: {...입력·중간값, notes: [...], caveats: [...]}}` — `caveats` 가 최상위에 **없다** |

여기에 봉투가 아예 없는 넷이 더 있다: `effective_rent.effective_rent` · `value.appraise` · `caprate.implied` · `refi.breakeven_vacancy` 는 **float 하나**를 돌려준다. 가정을 실을 자리가 없으므로 부르는 쪽이 문맥을 만들어야 한다 — `build_out` 이 `breakeven_vacancy` 옆에 `breakeven_context`(필요 NOI·만실 EGI)를 따로 붙여 두는 것이 그 예다. `value.error_dist` 는 dict 이지만 `caveats` 가 없다(분포 수치만).

### ③ JS 패리티 대상은 아홉 함수다

대시보드가 슬라이더로 가정을 바꿔 다시 계산하려면 아래 아홉을 JS 로 옮겨야 한다. 옮길 때 **물리 게이트와 오류 유형(ValueError/RuntimeError 구분)까지 함께 옮겨라** — 게이트 없는 JS 판은 파이썬이 막던 단위 오류를 그대로 화면에 그린다.

1. `effective_rent.effective_rent` — 렌트프리 차감
2. `effective_rent.building_adjust` — 연식·규모·역세권 보정
3. `noi.noi` — 전용률·공실·opex → NOI
4. `value.appraise` — NOI ÷ cap
5. `caprate.implied` — 실거래 역산 cap
6. `acquisition.max_loan` — 삼중 제약 대출가능액
7. `acquisition.hold_model` — 보유기간 지분 IRR
8. `refi.refi_test` — 만기 차환 판정
9. `refi.breakeven_vacancy` — 손익분기 공실률

`caprate.benchmark` 는 분기 계열을 통째로 받아야 해서 슬라이더 대상이 아니다(`out/market.json` 의 값을 그대로 읽으면 된다). **`pf.pf_model` 은 실험실 Ⅲ장(개발 PF 시뮬레이터)을 만들 때만** 열째로 추가한다 — 월별 스케줄까지 옮겨야 해서 나머지 아홉보다 품이 크다.

IRR 은 `fin_core.irr_annual` 의 이분법(구간 [−0.5, 1.0], 200회 고정 반복)을 그대로 옮겨야 같은 값이 나온다. 뉴턴법으로 바꾸면 수렴이 입력에 좌우돼 파이썬 산출과 미세하게 어긋난다. 유한성 가드도 한 벌(`fin_core.require_finite`)이니 JS 판도 한 벌로 두라.

## 파킹된 표기 정정(다음 터치 시 일괄)

- `docs/ledger-unlock-checklist.md`·`buildings.py` 독스트링의 "필지 공유 8동" → 실제 7동(IFC 3·파크원 2·마제스타 2).
- 스펙 §4 "50동" → 55동. `reits.py` 독스트링 div 예시 날짜 형식.
- tests/의 `open()` 인코딩 미명시 7곳.

## 엔진 최종 리뷰 파킹 목록 (계획 3 터치 시 정정)

- `build_out`: 빈 yield 계열 입력 시 진단이 TypeError로 강등(빌드는 정지 — 오답 출고는 없음). `_require_same_quarter` 앞에서 None 검사로 복원.
- `market.sub_regions.*`·`seoul_reference`: 권역 3종에 넣은 분기 정렬 단언(F1)과 동류의 구멍 잔존 — 같은 패턴 확장 적용.
- `pf.py:54`: D4 대안 3.3495억의 설명이 "마지막 달 인출 23.33억"으로 오귀속(실제는 마지막 달 잔액 669.9억의 한 달 이자). 상수는 정확.
