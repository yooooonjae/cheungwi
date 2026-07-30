"""한국은행 ECOS 금리 수집기: 국고채(10년)·CD(91일)·예금은행 기업대출 금리의 월 시계열.

실행: python3 src/collect/rates.py
산출: data/rates.json
  {"treasury10y":   [{"ym": "2026-06", "value": 3.12}, ...],   # 국고채 10년 월평균 유통수익률(연%)
   "cd91":          [{"ym": "2026-06", "value": 3.45}, ...],   # CD 91일 월평균 유통수익률(연%)
   "loan_corp_new": [{"ym": "2026-06", "value": 4.31}, ...],   # 예금은행 기업대출 금리, 신규취급액(연%)
   "meta": {...}}

층위에서 이 세 계열이 맡는 몫: 국고채 10년은 캡레이트 스프레드의 무위험 기준선,
CD 91일은 변동금리 대출의 지표금리, 기업대출 금리(신규)는 실제 조달비용의 대용치다.

통계코드는 2026-07-30 ECOS StatisticItemList·StatisticTableList 실측으로 확정했다.
  721Y001 "1.3.2.2. 시장금리(월,분기,년)"          — 5050000 국고채(10년), 2010000 CD(91일)
  121Y006 "1.3.3.2.1. 예금은행 대출금리(신규취급액 기준)" — BECBLA02 기업대출
계획서 초안이 기업대출 후보로 적은 BECBLA0301 은 실제로는 가계대출 하위의
"소액대출(500만원 이하)"이라 기업 조달비용과 무관하다 — BECBLA02 로 바로잡았다.
(같은 저장소 계열의 기존 수집기 /Users/iseul/개발/src/collect/ecos.py 도 기업대출에 BECBLA02 를 쓴다.)

수집 원칙(Task 3에서 얻은 교훈):
  - 페이지 합계가 list_total_count 와 다르면 조용히 넘기지 않고 RuntimeError 로 멈춘다.
  - 오류·불완전 응답은 캐시에 기록하지 않는다. 직전 성공본이 남아 절단본에 덮이지 않는다.
  - 월 시계열은 실행할 때마다 최신 월이 늘어나므로 캐시가 있어도 API를 다시 부른다.
    data/raw/rates/{계열키}.json 은 원본 감사용 사본이지 호출 생략 스위치가 아니다.
"""

import datetime
import json
import sys
import time
from pathlib import Path

if __package__ in (None, ""):  # 스크립트로 직접 실행할 때만 저장소 루트를 경로에 올린다
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.collect.common import ROOT, api_get, call_with_backoff, load_config  # noqa: E402

RAW_DIR = ROOT / "data" / "raw" / "rates"
OUT_PATH = ROOT / "data" / "rates.json"
BASE = "https://ecos.bok.or.kr/api/StatisticSearch"

START = "201501"  # 표본 시작월 — 2015-01 이후만 모은다
CYCLE = "M"
PSIZE = 1000  # 한 번에 받는 행수(2015-01 이후 월 시계열은 200행 미만이라 사실상 1페이지)
CALL_GAP = 0.3
MIN_MONTHS = 120  # 계열별 최소 개월 수 게이트(10년)
VALUE_RANGE = (0.0, 20.0)  # 금리 % 물리 범위

# (계열키, 통계표코드, 항목코드, 설명)
SERIES = [
    ("treasury10y", "721Y001", "5050000", "국고채(10년) 월평균 유통수익률"),
    ("cd91", "721Y001", "2010000", "CD(91일) 월평균 유통수익률"),
    ("loan_corp_new", "121Y006", "BECBLA02", "예금은행 기업대출 금리(신규취급액 기준)"),
]


def parse_ecos(payload: dict) -> list:
    """ECOS StatisticSearch 응답 → [{"ym": "YYYY-MM", "value": float}] 월 시계열(순수 함수).

    데이터가 없는 응답(RESULT 만 온 INFO-200 등)은 빈 목록이다 — 오류 판정은 호출자 몫이다.
    TIME 이 "YYYYMM" 이 아니거나 DATA_VALUE 를 float 으로 못 읽는 행(결측월의 ""·"-"·null)은
    0.0 으로 뭉개지 않고 행째로 버린다. 버린 행수는 collect() 가 meta.skipped 에 적는다.
    """
    body = payload.get("StatisticSearch")
    if not body:
        return []
    points = []
    for row in body.get("row") or []:
        stamp = (row.get("TIME") or "").strip()
        if len(stamp) != 6 or not stamp.isdigit() or not 1 <= int(stamp[4:]) <= 12:
            continue
        try:
            value = float(row.get("DATA_VALUE"))
        except (TypeError, ValueError):
            continue
        points.append({"ym": f"{stamp[:4]}-{stamp[4:]}", "value": value})
    points.sort(key=lambda p: p["ym"])
    return points


def _mask(text: str, key: str) -> str:
    """오류 본문에 인증키가 섞여 나와도 로그·보고서에 남지 않게 가린다."""
    return text.replace(key, "***") if key else text


def _get_page(stat: str, item: str, start: str, end: str, first: int, last: int) -> dict:
    """StatisticSearch 한 페이지 → 응답 dict. HTTP 비정상은 예외로 드러낸다(삼킴 금지)."""
    key = load_config()["ecos_key"]
    url = f"{BASE}/{key}/json/kr/{first}/{last}/{stat}/{CYCLE}/{start}/{end}/{item}"
    status, text = call_with_backoff(lambda: api_get(url, {}, retries=1), tries=4)
    time.sleep(CALL_GAP)
    if status != 200:
        raise RuntimeError(
            f"ECOS HTTP {status} ({stat}/{item} {first}~{last}행): {_mask(text, key)[:800]}")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:  # 200인데 JSON이 아닌 본문(게이트웨이 오류 페이지 등)
        raise RuntimeError(
            f"ECOS 응답이 JSON이 아니다 ({stat}/{item}): {_mask(text, key)[:400]}") from e


def _rows(payload: dict, where: str) -> tuple:
    """응답 → (list_total_count, 행 목록). INFO-200(데이터 없음)만 빈 결과로 받아들인다."""
    body = payload.get("StatisticSearch")
    if body is None:
        result = payload.get("RESULT") or {}
        if result.get("CODE") == "INFO-200":
            return 0, []
        raise RuntimeError(f"ECOS 비정상 응답 {where}: {result or str(payload)[:400]}")
    return int(body["list_total_count"]), list(body.get("row") or [])


def _check_item(name: str, item: str, rows: list):
    """요청한 항목코드가 아닌 행이 섞였는지 확인 — 코드가 틀리면 조용한 오염 대신 실패시킨다."""
    others = sorted({r.get("ITEM_CODE1") for r in rows
                     if r.get("ITEM_CODE1") and r.get("ITEM_CODE1") != item})
    if others:
        raise RuntimeError(f"{name}: 요청 항목 {item} 외의 항목이 섞였다 {others}")


def _fetch_series(name: str, stat: str, item: str, start: str, end: str) -> dict:
    """한 계열의 전 페이지를 ECOS 응답 모양 그대로 모아 돌려준다. 성공 응답만 캐시한다.

    받은 행수가 list_total_count 와 다르면(중간 페이지가 조용히 빈 경우) 절단본을 캐시에
    남기지 않고 RuntimeError 로 멈춘다 — 절단본이 박제되면 이후 실행이 계속 그것을 읽는다.
    """
    where = f"{name}({stat}/{item})"
    total, rows = _rows(_get_page(stat, item, start, end, 1, PSIZE), where)
    page = 2
    while len(rows) < total:
        _, more = _rows(
            _get_page(stat, item, start, end, (page - 1) * PSIZE + 1, page * PSIZE), where)
        if not more:
            break
        rows.extend(more)
        page += 1
    if total == 0 or not rows:
        raise RuntimeError(f"{where}: {start}~{end} 구간에 행이 하나도 없다. 캐시를 기록하지 않는다.")
    if len(rows) != total:
        raise RuntimeError(
            f"{where}: 응답 절단 — list_total_count {total}인데 {len(rows)}행만 받았다"
            f"(마지막 응답 페이지 {page - 1}, 페이지당 {PSIZE}행, 마지막 행 "
            f"{rows[-1].get('TIME')}). 캐시를 기록하지 않는다.")
    _check_item(name, item, rows)
    payload = {"StatisticSearch": {"list_total_count": total, "row": rows}}
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False),
                                          encoding="utf-8")
    return payload


def _months(first: str, last: str) -> list:
    """'2015-01'~'2026-06' 사이의 모든 월 키."""
    y, m = int(first[:4]), int(first[5:])
    out = []
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _validate(name: str, series: list):
    """저장 전 게이트: 개월 수·값 범위·월 연속성. 하나라도 어긋나면 시끄럽게 멈춘다."""
    if len(series) < MIN_MONTHS:
        raise RuntimeError(f"{name}: 개월 수 부족 {len(series)} < {MIN_MONTHS}")
    lo, hi = VALUE_RANGE
    bad = [p for p in series if not lo <= p["value"] <= hi]
    if bad:
        raise RuntimeError(f"{name}: 금리 범위({lo}~{hi}%) 밖 {bad[:3]}")
    months = [p["ym"] for p in series]
    dups = sorted({m for m in months if months.count(m) > 1})
    if dups:
        raise RuntimeError(f"{name}: 같은 월이 두 번 {dups[:6]}")
    missing = sorted(set(_months(months[0], months[-1])) - set(months))
    if missing:
        raise RuntimeError(f"{name}: 월이 비었다 {missing[:6]}{'…' if len(missing) > 6 else ''}")


def collect() -> None:
    end = datetime.date.today().strftime("%Y%m")
    out, skipped, counts, names, units = {}, {}, {}, {}, {}
    for name, stat, item, desc in SERIES:
        payload = _fetch_series(name, stat, item, START, end)
        series = parse_ecos(payload)
        _validate(name, series)
        raw_rows = len(payload["StatisticSearch"]["row"])
        out[name] = series
        skipped[name] = raw_rows - len(series)
        counts[name] = len(series)
        names[name] = desc
        units[name] = payload["StatisticSearch"]["row"][0].get("UNIT_NAME") or "연%"
        print(f"  {name:<14} {len(series):>4}개월  {series[0]['ym']}~{series[-1]['ym']}  "
              f"최신={series[-1]['value']}%  버린 행 {skipped[name]}  ({desc})")

    result = {
        **out,
        "meta": {
            "stat_codes": {name: [stat, item] for name, stat, item, _ in SERIES},
            "series_names": names,
            "start": START,
            "end": end,
            "cycle": CYCLE,
            "counts": counts,
            "skipped": skipped,  # TIME 형식 불량·DATA_VALUE float 캐스팅 실패로 버린 행수
            "units": units,
            "collected_at": datetime.date.today().isoformat(),
            "source": "한국은행 ECOS",
            "note": ("국고채·CD는 721Y001 시장금리(월평균 유통수익률), 기업대출은 121Y006 "
                     "예금은행 대출금리(신규취급액 기준)의 기업대출 항목이다. 잔액기준(121Y002)이 "
                     "아니므로 신규 조달 여건을 본다."),
        },
    }
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  저장: {OUT_PATH} ({START}~{end}, 3계열)")


def main() -> None:
    # 이 수집기는 부분 저장 경로가 없다 — _validate 가 어긋나면 그 자리에서 예외로 멈추므로
    # 저장까지 도달했다는 것 자체가 완주다. 마커를 main() 에 두는 건 테스트가 부르기 위해서다.
    print("ECOS 금리 수집:")
    collect()
    print("COMPLETE")


if __name__ == "__main__":
    main()
