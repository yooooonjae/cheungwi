# 건축물대장 승인 후 체크리스트

2026-07-30 현재 `BldRgstHubService` 는 전 오퍼레이션이 평문 403 Forbidden 이다(같은
service_key 로 RTMS·ArchPmsHubService 는 200). data.go.kr 활용신청이 승인되면 대장이 열리고,
그때 비로소 확인·수정할 수 있는 일이 아래에 모여 있다. **승인 전에는 어느 항목도 검증할 수
없으므로 미뤄 둔 것이지, 안 해도 되는 일이 아니다.** 순서는 대체로 실행 순서다.

데이터 계층 최종 리뷰(2026-07-30)가 병합 조건이 아닌 후속 필수로 남긴 목록이다. 커밋되지 않은
채로 두면 그대로 잊히므로 문서로 박아 둔다.

---

## 1. 연속 `LedgerTransient` 3회 → 저장 후 `RESUME_NEEDED` 서킷브레이커

`src/collect/buildings.py` 의 수집 루프는 일시 오류(봉투 04·05·21)를 건별로 격리하고 계속
간다. 서버가 통째로 흔들리는 동안 55동을 다 돌면 전 동이 `failed` 로 채워진 산출이 저장되고
마커는 `RESUME_NEEDED` 가 되는데, 이때 문제는 마커가 아니라 **55회의 헛호출**이다.
연속 실패 카운터를 두고 3회에서 끊은 뒤 지금까지의 결과를 저장하고 `RESUME_NEEDED` 로
끝내야 한다. `trades.py` 의 `MAX_FAIL_STREAK` 이 참고형이다.

## 2. `unknown` 봉투 분류 — 저장 없는 전역 사망 경로 봉합

`_raise_for_envelope()` 의 마지막 줄은 성격을 판정하지 못한 봉투를 맨 `RuntimeError` 로
올린다. 이 예외는 `collect()` 의 `except` 어디에도 걸리지 않아 **저장에 도달하지 못하고
프로세스가 죽는다** — 그때까지 받은 VWorld·대장이 전부 버려진다는 뜻이다. 알 수 없는 봉투는
"모른다"는 사실 자체가 정보이므로, 건별 격리(그 동만 `failed`)로 내리고 산출 meta 에 미상
봉투 코드를 남겨 다음 실행이 이어받게 해야 한다. 대장이 열리면 지금까지 못 본 봉투 코드가
쏟아질 수 있어 승인 직후가 이 구멍을 밟기 가장 쉬운 시점이다.

## 3. `buildings.py` 모듈 독스트링 드리프트 정정

독스트링의 "── 2026-07-30 현재 대장 API는 잠겨 있다 ──" 절은 승인되는 순간 사실이 아니게 된다.
403 진단 기록은 이 문서로 옮기고(위 머리말), 독스트링에는 열린 뒤의 동작 — 캐시된 VWorld 는
재호출 없이 통과하고 대장만 채운다는 재개 규약 — 만 남긴다. 산출 `meta.note` 와
`data/DATA_MANIFEST.json` 의 buildings 커버리지 문구(`대장 0/55`)도 같이 확인한다.

## 4. fixture 를 역삼동 737 실응답으로 교체

`tests/fixtures/bldrgst_item_sample.xml` · `bldrgst_shared_parcel_sample.xml` 은 403 때문에
실응답을 못 받아 응답 스펙만 보고 손으로 지어낸 것이다. 승인 후 **역삼동 737(강남파이낸스센터)**
의 실제 표제부 응답으로 갈아 끼운다. 태그 순서·빈 값 표기·`numOfRows` 초과 시의 페이지 모양처럼
지어낸 fixture 가 결코 재현하지 못하는 것들이 파서의 실제 실패 지점이다.

## 5. `mgmBldrgstPk` 실태그명 확인 — 비면 중복 탐지가 무력화된다

`duplicate_assignments()` 는 두 시드가 같은 대장 동을 집었는지를 오직 `mgmBldrgstPk` 값으로
판정한다. 이 태그명이 실응답에서 다르거나 빈 문자열로 오면 **중복 탐지가 조용히 0건이 된다** —
막으려던 사고가 그대로 통과하는데 경고는 한 줄도 안 나온다. 실응답에서 태그명과 값의 존재를
먼저 확인하고, 비어 있으면 그 사실을 flags 로 올리도록 고친다(빈 키를 같은 키로 묶지 않는 것도
함께 확인).

## 6. 첫 실행 후 IFC 3동·파크원 2동·마제스타 2동 확인

필지를 공유하는 시드가 세 묶음 있다. 대장이 열린 첫 실행 결과에서 이 8동의
`match_method` 와 `meta.duplicate_ledger` 를 눈으로 본다.

| 필지 | 시드 |
|---|---|
| 여의도동 23 | `ifc-one` · `ifc-two` · `ifc-three` |
| 여의도동 22 | `parc1-tower1` · `parc1-tower2` |
| 서초동 1498-5 | `majesta-city-tower1` · `majesta-city-tower2` |

`match_method` 가 `fallback` 이면 이름이 안 걸려 필지 전체에서 연면적으로 고른 것이라 믿을 수
없고, `duplicate_ledger` 에 오르면 두 시드가 같은 동을 집은 사고다. 어느 쪽이든 시드
`aliases` 를 고쳐 동을 갈라야 한다.

## 7. `trades.py --rebuild` 로 매칭 승격

지금 실거래 매칭의 `kind` 는 전부 `jibun_only` 다 — 연면적을 몰라 통매각(`whole`)과
구분소유(`partial`)를 가를 수 없기 때문이다(`meta.ledger_ready = false`). 대장이 채워진 뒤
`python3 src/collect/trades.py --rebuild` 를 돌리면 **네트워크를 쓰지 않고** raw 캐시만으로
산출을 다시 만들며 `whole`/`partial` 로 승격된다. 이어서 `make manifest` 로 원장을 갱신하고
`make test` 로 커버리지 문구까지 확인한다.
