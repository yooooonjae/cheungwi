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

## 파킹된 표기 정정(다음 터치 시 일괄)

- `docs/ledger-unlock-checklist.md`·`buildings.py` 독스트링의 "필지 공유 8동" → 실제 7동(IFC 3·파크원 2·마제스타 2).
- 스펙 §4 "50동" → 55동. `reits.py` 독스트링 div 예시 날짜 형식.
- tests/의 `open()` 인코딩 미명시 7곳.
