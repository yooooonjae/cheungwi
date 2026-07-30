"""한국부동산원 R-ONE 오피스 임대동향 수집기: 서울 3대 권역(도심·강남·여의도마포) 분기 시계열.

실행: python3 src/collect/rone_office.py
산출: data/rone_office.json
  {"regions":     {"도심"|"강남"|"여의도마포"|"서울": {"rent_index": [{"yq","value"}...],   # 지수(2024.2Q=100)
                                                      "vacancy":    [{"yq","value"}...],   # 공실률 %
                                                      "rent_level": [{"yq","value"}...],   # 임대료 천원/㎡
                                                      "yield":      [{"yq","income","capital","total"}...]}},  # %
   "sub_regions": {"서울>도심>광화문": {같은 4계열}, ...},   # 3대 권역의 하위 상권
   "meta": {...}}

R-ONE 구조(SttsApiTblData 실측):
  - 상업용 임대동향은 분기(QY). WRTTIME_IDTFR_ID = "YYYYQQ"(예 202601 = 2026년 1분기).
  - 지역축(CLS)은 3단 계층이고 CLS_FULLNM 의 '>' 개수가 곧 깊이다.
      0단 "서울"(시도) · 1단 "서울>도심"(권역, CLS_ID 510003/510004/510005) · 2단 "서울>도심>광화문"(상권).
    시도 지표만 쓰는 기존 rone_commercial 과 반대로, 층위의 본체는 1단 권역 행이다.
  - 지수는 기준시점 재설정(rebase) 때문에 기간별 표가 나뉘나, '임대가격지수(시계열)' 표가
    2013Q1~현재를 단일 기준(2024.2Q=100)으로 연결 제공 → 지수는 시계열 표 1개만 쓴다.
  - 공실률·임대료·수익률은 레벨값이라 rebase 무관 → 기간별 표(2013~2016 … 2024Q3~)를
    STATBL_ID 순서대로 이어 붙인다(stitch). 같은 분기가 겹치면 뒤 표(더 최근 개정)의 값을 쓴다.
  - 수익률표는 소득/자본/투자 3개 항목(ITM)을 한 표에 수록 → 같은 분기 행을 한 점으로 병합한다.
원본 응답은 data/raw/rone_office/ 에 STATBL_ID 단위로 전량 캐시한다(재실행 시 API 재호출 없음).
"""

import datetime
import json
import sys
import time
from pathlib import Path

if __package__ in (None, ""):  # 스크립트로 직접 실행할 때만 저장소 루트를 경로에 올린다
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.collect.common import ROOT, api_get, call_with_backoff, load_config  # noqa: E402

RAW_DIR = ROOT / "data" / "raw" / "rone_office"
OUT_PATH = ROOT / "data" / "rone_office.json"
BASE = "https://www.reb.or.kr/r-one/openapi"
YEARS = 10  # 최근 10년치만 보관
CALL_GAP = 0.3
PSIZE = 1000  # R-ONE pSize 상한(초과 시 ERROR-336)

SIDO = "서울"
# 권역 레벨(CLS_FULLNM 에 '>' 1개)의 실측 CLS_ID. 510006 '서울>기타'는 층위 범위 밖이라 버린다.
REGION_CLS_ID = {"도심": 510003, "강남": 510004, "여의도마포": 510005}
CLS_ID_TO_REGION = {v: k for k, v in REGION_CLS_ID.items()}
REGION_ORDER = ["도심", "강남", "여의도마포", SIDO]
SERIES = ("rent_index", "vacancy", "rent_level", "yield")

# (계열, STATBL_ID 목록, 표명). 목록이 여럿이면 기간표 stitch.
TABLES = [
    ("rent_index", ["TT244963134453269"],
     "임대동향 지역별 임대가격지수(시계열)_오피스"),
    ("vacancy",
     ["A_2024_00238", "A_2024_00241", "A_2024_00244", "A_2024_00247",
      "A_2024_00250", "A_2024_00253", "TT244763134428698"],
     "임대동향 지역별 공실률_오피스(2013~2026, 기간표 stitch)"),
    ("rent_level",
     ["A_2024_00257", "A_2024_00261", "A_2024_00265", "A_2024_00269",
      "A_2024_00273", "A_2024_00277", "TT249843134237374"],
     "임대동향 지역별 임대료(천원/㎡)_오피스(2013~2026, 기간표 stitch)"),
    ("yield",
     ["A_2024_00346", "A_2024_00350", "A_2024_00354", "A_2024_00358",
      "A_2024_00362", "A_2024_00366", "T245883135037859"],
     "임대동향 수익률(분기, 소득/자본/투자)_오피스(2013~2026, 기간표 stitch)"),
]
YIELD_ITM = {"소득수익률": "income", "자본수익률": "capital", "투자수익률": "total"}
YIELD_FIELDS = ("income", "capital", "total")

# 계열별 값 허용 범위(저장 전 물리 게이트). rent_level 은 양수 조건만.
VALUE_RANGE = {"rent_index": (20.0, 200.0), "vacancy": (0.0, 50.0), "yield": (-10.0, 20.0)}


def _cutoff_yq() -> str:
    """10년 전 분기 키(YYYYQQ). 예: 2026Q3 기준 → '201603'."""
    t = datetime.date.today()
    q = (t.month - 1) // 3 + 1
    return f"{t.year - YEARS}{q:02d}"


def _yq(wrttime: str) -> str:
    """'202601' → '2026Q1'."""
    return f"{wrttime[:4]}Q{int(wrttime[4:])}"


def _classify(row: dict):
    """행 → ('regions'|'sub_regions', 키) 또는 None(버림).

    서울 시도 행·3대 권역 행·3대 권역의 하위 상권 행만 남긴다.
    '서울>기타'(510006)와 그 하위 상권, 타 시도는 층위 범위 밖이라 버린다.
    """
    parts = (row.get("CLS_FULLNM") or "").split(">")
    if parts[0] != SIDO:
        return None
    if len(parts) == 1:
        return "regions", SIDO
    if len(parts) == 2:
        region = CLS_ID_TO_REGION.get(row.get("CLS_ID"))
        return ("regions", region) if region else None
    if len(parts) == 3 and parts[1] in REGION_CLS_ID:
        return "sub_regions", ">".join(parts)
    return None


def parse_rows(tagged_rows: list) -> dict:
    """[(계열명, R-ONE 행), ...] → {"regions": …, "sub_regions": …}(순수 함수).

    같은 (지역, 계열, 분기)가 여러 번 오면 나중 행이 이긴다 — 기간표 stitch가 여기서 이뤄지므로
    호출자는 STATBL_ID를 오래된 표부터 순서대로 넘겨야 한다.
    """
    acc = {}  # (버킷, 키, 계열) -> {WRTTIME: 값 또는 {income,capital,total}}
    for series, row in tagged_rows:
        hit = _classify(row)
        if hit is None:
            continue
        wrttime = row.get("WRTTIME_IDTFR_ID")
        value = row.get("DTA_VAL")
        if not wrttime or value is None:
            continue
        slot = acc.setdefault((hit[0], hit[1], series), {})
        if series == "yield":
            field = YIELD_ITM.get(row.get("ITM_NM"))
            if field is None:
                continue
            slot.setdefault(wrttime, {})[field] = round(float(value), 4)
        else:
            slot[wrttime] = round(float(value), 4)

    out = {"regions": {}, "sub_regions": {}}
    for (bucket, key, series), wmap in acc.items():
        entry = out[bucket].setdefault(key, {s: [] for s in SERIES})
        points = []
        for wrttime, value in sorted(wmap.items()):
            if series == "yield":
                point = {"yq": _yq(wrttime)}
                point.update({f: value[f] for f in YIELD_FIELDS if f in value})
            else:
                point = {"yq": _yq(wrttime), "value": value}
            points.append(point)
        entry[series] = points
    # 출력 순서 고정: 권역은 도심·강남·여의도마포·서울, 하위 상권은 이름순
    out["regions"] = {k: out["regions"][k] for k in REGION_ORDER if k in out["regions"]}
    out["sub_regions"] = dict(sorted(out["sub_regions"].items()))
    return out


def _get_page(statbl_id: str, page: int) -> tuple:
    """SttsApiTblData.do 한 페이지 → (total, rows). 오류 삼킴 금지(비정상은 예외)."""
    params = {"KEY": load_config()["rone_key"], "Type": "json", "STATBL_ID": statbl_id,
              "DTACYCLE_CD": "QY", "pIndex": str(page), "pSize": str(PSIZE)}
    status, text = call_with_backoff(
        lambda: api_get(f"{BASE}/SttsApiTblData.do", params, retries=1), tries=4)
    time.sleep(CALL_GAP)
    if status != 200:
        raise RuntimeError(f"R-ONE HTTP {status} ({statbl_id} p{page}): {text[:800]}")
    doc = json.loads(text)
    obj = doc.get("SttsApiTblData")
    if obj is None:  # RESULT만 온 응답
        code = doc.get("RESULT", {}).get("CODE")
        if code == "INFO-200":  # 데이터 없음 — 마지막 페이지 다음
            return 0, []
        raise RuntimeError(f"R-ONE 비정상 응답 {statbl_id}: {text[:800]}")
    head = obj[0]["head"]
    result = head[1]["RESULT"]
    if result["CODE"] != "INFO-000":
        raise RuntimeError(f"R-ONE 오류 {statbl_id}: {result}")
    return int(head[0]["list_total_count"]), list(obj[1]["row"])


def _fetch_table(statbl_id: str) -> list:
    """한 표의 전체 분기 행(전 페이지). STATBL_ID 단위 캐시 — 오류 응답은 캐시하지 않는다."""
    cache = RAW_DIR / f"{statbl_id}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    total, rows = _get_page(statbl_id, 1)
    page = 2
    while len(rows) < total:
        _, more = _get_page(statbl_id, page)
        if not more:
            break
        rows.extend(more)
        page += 1
    cache.write_text(json.dumps(rows, ensure_ascii=False))
    return rows


def _check_items(series: str, statbl_id: str, rows: list):
    """표의 ITM 구성 점검. 단일항목 계열에 항목이 섞이면 stitch가 값을 뒤섞으므로 즉시 실패시킨다."""
    items = {r.get("ITM_NM") for r in rows}
    if series == "yield":
        missing = set(YIELD_ITM) - items
        if missing:
            raise RuntimeError(f"{statbl_id}: 수익률 항목 누락 {sorted(missing)} (수록 {sorted(items)})")
    elif len(items) > 1:
        raise RuntimeError(f"{statbl_id}: {series} 표에 항목이 여럿 {sorted(items)}")


def _coverage(parsed: dict) -> dict:
    """계열별 권역 커버리지 {계열: {권역: 분기 수}} — 권역 행이 없는 계열을 meta에 드러낸다."""
    return {series: {name: len(parsed["regions"].get(name, {}).get(series, []))
                     for name in REGION_ORDER}
            for series in SERIES}


def _validate(parsed: dict):
    """저장 전 물리 게이트: 3대 권역 지수 20분기 이상, 공실률 0~50%, 수익률 -10~20%, 임대료 양수."""
    for name in REGION_CLS_ID:
        n = len(parsed["regions"].get(name, {}).get("rent_index", []))
        assert n >= 20, f"{name}: 임대가격지수 분기 수 부족 {n}"
    for bucket in ("regions", "sub_regions"):
        for key, entry in parsed[bucket].items():
            for series in SERIES:
                for point in entry[series]:
                    where = f"{key}/{series}@{point['yq']}"
                    if series == "yield":
                        lo, hi = VALUE_RANGE["yield"]
                        for field in YIELD_FIELDS:
                            if field in point:
                                assert lo <= point[field] <= hi, f"{where}: 범위 밖 {field}={point[field]}"
                    elif series == "rent_level":
                        assert point["value"] > 0, f"{where}: 임대료 비양수 {point['value']}"
                    else:
                        lo, hi = VALUE_RANGE[series]
                        assert lo <= point["value"] <= hi, f"{where}: 범위 밖 {point['value']}"


def collect() -> dict:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = _cutoff_yq()
    tagged, tables_used = [], []
    for series, ids, name in TABLES:
        for statbl_id in ids:
            rows = _fetch_table(statbl_id)
            _check_items(series, statbl_id, rows)
            tagged += [(series, r) for r in rows
                       if (r.get("WRTTIME_IDTFR_ID") or "") >= cutoff]
        tables_used.append({"series": series, "id": "+".join(ids), "name": name})

    parsed = parse_rows(tagged)
    _validate(parsed)
    coverage = _coverage(parsed)
    empty = [s for s in SERIES
             if all(coverage[s][name] == 0 for name in REGION_CLS_ID)]
    result = {
        "regions": parsed["regions"],
        "sub_regions": parsed["sub_regions"],
        "meta": {
            "region_cls_id": REGION_CLS_ID,
            "tables_used": tables_used,
            "collected_at": datetime.date.today().isoformat(),
            "source": "한국부동산원 R-ONE 상업용부동산 임대동향조사",
            "note": "여의도 권역의 R-ONE 공식 명칭은 '여의도마포' 합성 권역",
            "window": f"{_yq(cutoff)} 이후 10년",
            "units": {"rent_index": "지수(2024.2Q=100)", "vacancy": "%",
                      "rent_level": "천원/㎡(임대면적 기준 월 임대료)",
                      "yield": "%(분기, 소득·자본·투자수익률)"},
            "coverage": coverage,
            "series_without_region_rows": empty,
            "excluded": "'서울>기타'(CLS_ID 510006)와 그 하위 상권, 서울 외 시도 전 행",
            "caveat": ("하위 상권 명칭은 기간표마다 조금씩 다르다(예 2016년 이전 '서울>강남>신사'가 "
                       "이후 '서울>강남>신사역'). CLS_FULLNM 을 키로 그대로 두므로 같은 상권이 "
                       "두 키로 갈릴 수 있다 — 하위 상권 시계열을 이어 쓸 때는 명칭 매핑이 필요하다."),
        },
    }
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return {"path": str(OUT_PATH), "cutoff": cutoff, "coverage": coverage,
            "empty_series": empty, "parsed": parsed}


def _fmt(series: str, entry: dict) -> str:
    points = entry[series]
    if not points:
        return f"{series:<11} 0분기 (행 없음)"
    last = points[-1]
    value = (f"소득{last.get('income')}/자본{last.get('capital')}/투자{last.get('total')}"
             if series == "yield" else last.get("value"))
    return (f"{series:<11} {len(points):>2}분기  {points[0]['yq']}~{last['yq']}  최신={value}")


if __name__ == "__main__":
    print("R-ONE 오피스 권역 지표 수집:")
    r = collect()
    for name in REGION_ORDER:
        entry = r["parsed"]["regions"].get(name)
        print(f"  [{name}]" + ("" if entry else " 행 없음"))
        for series in SERIES:
            if entry:
                print("    " + _fmt(series, entry))
    subs = r["parsed"]["sub_regions"]
    print(f"  하위 상권 {len(subs)}개: {', '.join(sorted(subs))}")
    if r["empty_series"]:
        print(f"  ⚠ 권역 행이 전혀 없는 계열: {r['empty_series']}")
    print(f"  저장: {r['path']} (기준 {r['cutoff']} 이후)")
    print("COMPLETE")
