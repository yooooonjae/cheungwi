"""상업업무용 실거래 수집기 — 국토부 RTMS(RTMSDataSvcNrgTrade), 서울 5개 구 2006-01~현재.

실행: python3 src/collect/trades.py [--rebuild] [--limit N]
산출: data/trades.json · data/trades_progress.json(중단 재개)
원시: data/raw/trades/nrg_{sgg}_{ym}_p{n}.xml — 전 용도 원문 그대로

── 수집과 매칭을 분리한다 ───────────────────────────────────────────────────
raw 캐시가 단일 진실이고 trades.json은 그것을 다시 읽어 만든 파생물이다. 그래서 이 수집기는
매 실행마다 **캐시 전체를 다시 읽어 trades.json을 새로 만든다.** 대장(buildings.json의
ledger)이 채워진 뒤 다시 돌리면 API를 한 번도 부르지 않고 match.kind가 jibun_only에서
whole/partial로 승격된다(`--rebuild`는 네트워크를 아예 쓰지 않는다).
2026-07-30 현재 대장 API 활용신청이 승인되지 않아 buildings.json 55행의 ledger가 전부 null이다
— 파일이 있어도 ledger가 null이면 면적비를 낼 수 없으므로 kind는 jibun_only다.

── 지번은 마스킹돼 온다 ─────────────────────────────────────────────────────
응답의 jibun은 '7*'·'1**'처럼 뒷자리가 가려져 온다(실측 380개 값 중 20개가 마스킹형).
그래서 매칭은 같은 시군구·법정동 안에서 마스크를 정규식으로 푼 fullmatch로 한다. 이건
**한 동을 특정한다는 보장이 없다** — '7*'는 737에도 790에도 걸린다. 후보가 여럿이면
match.building_id는 **null**이고 후보 목록만 match.candidates에 남는다. 첫 후보를 고르면
서초동 '1***' 1,688행이 통째로 한 동에 붙어 버린다 — 고르지 못하는 자리에서는 고르지 않는다.
지번이 통째로 '*'인 행(정보량 0)은 아무 동에도 매칭하지 않는다.

── 부분 수집이 완성본을 덮어쓰지 않는다 ─────────────────────────────────────
raw 캐시는 커밋하지 않고 산출 JSON만 커밋한다. 그래서 새로 clone한 곳의 캐시는 비어 있는 게
정상이고, 거기서 첫 실행은 쿼터·시간 때문에 반드시 일부만 받는다. 그 결과로 1,235셀짜리
trades.json을 0셀로 덮어쓰면 커밋된 데이터가 조용히 사라진다. 그래서 이번 실행이 기존 산출보다
얇으면 data/trades.partial.json 으로 비켜 쓰고 원본에 손대지 않는다(save_result 참조).

── 쿼터를 태우지 않는다 ─────────────────────────────────────────────────────
셀 하나에서 쿼터 소진(HTTP 200 + LIMITED_NUMBER_OF_SERVICE_REQUESTS 봉투)을 만나면 그
자리에서 저장하고 RESUME_NEEDED로 끝낸다. 남은 셀을 계속 두드리면 다음 날 몫까지 태운다
(G2B에서 폴백 재시도가 일일 쿼터 90분을 태운 실사고가 있었다). 재실행이 이어받는다.
"""

import datetime
import json
import os
import re
import shutil
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

if __package__ in (None, ""):  # 스크립트로 직접 실행할 때만 저장소 루트를 경로에 올린다
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.collect.common import (ROOT, SEOUL_GU, api_get, call_with_backoff,  # noqa: E402
                                classify_envelope, envelope_error, load_config)

URL = "https://apis.data.go.kr/1613000/RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade"

SEED_PATH = ROOT / "data" / "seed_buildings.json"
BUILDINGS_PATH = ROOT / "data" / "buildings.json"
OUT_PATH = ROOT / "data" / "trades.json"
PARTIAL_PATH = ROOT / "data" / "trades.partial.json"   # 기존 산출보다 얇은 결과가 비켜 가는 자리
PROG_PATH = ROOT / "data" / "trades_progress.json"
RAW_DIR = ROOT / "data" / "raw" / "trades"

# 이미 받아 둔 남의 캐시(수지 프로젝트, 같은 엔드포인트·같은 numOfRows). 강남 최근 36개월이 있다.
SUJI_RAW = (Path(os.environ.get("SUJI_DIR", str(Path.home() / "개발")))
            / "data" / "raw" / "rtms_commercial")

SGG_LIST = ["11110", "11140", "11560", "11650", "11680"]  # 종로·중·영등포·서초·강남
START_YM = "200601"        # RTMS 상업업무용 공표 개시(11680 200601 = 98건, 실측)

PER_PAGE = 1000
CALL_GAP = 0.25
SAVE_EVERY = 50            # 이만큼 호출할 때마다 진행 저장(중단 손실 최소화)
TIMEOUT = 30

MAX_FAIL_STREAK = 10       # 이만큼 연속으로 실패하면 서버가 앓는 것이다 — 저장하고 물러난다
OFFICE_USE = "업무"        # trades에 남기는 유일한 용도. 나머지 용도는 raw 캐시로만 보존한다.
# ㎡당 가격 물리 게이트(원). 하한 30만은 파싱·단위 오류와 지분거래 왜곡, 상한 2억은 건물 기준
# 상식 상한이다(수지 rtms_commercial의 nrg 범위와 동일한 근거).
GATE = (300_000, 200_000_000)
WHOLE_RATIO = 0.8          # 거래면적/연면적이 이 이상이면 '건물 통째' 거래로 본다

# 응답 item의 22개 태그(실측). 파서가 무엇을 보고 무엇을 버리는지 한눈에 두려고 적어 둔다.
#   쓰는 것 : sggCd umdNm jibun buildingUse buildingType dealYear dealMonth dealDay dealAmount
#             buildingAr plottageAr floor buildYear dealingGbn slerGbn buyerGbn cdealType
#             shareDealingType
#   안 쓰는 것: sggNm(코드로 갈음) estateAgentSggNm landUse cdealDay


# ── 순수 함수 ────────────────────────────────────────────────────────────────

def month_range(start: str = START_YM, end: str = None) -> list:
    """'200601'~'202607' 같은 월 문자열 목록(오름차순, 양끝 포함)."""
    if end is None:
        today = datetime.date.today()
        end = f"{today.year}{today.month:02d}"
    y, m = int(start[:4]), int(start[4:])
    ey, em = int(end[:4]), int(end[4:])
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _num(text, cast):
    """공백·콤마를 걷어낸 뒤 캐스팅. 비었거나 숫자가 아니면 None(0으로 눙치지 않는다)."""
    s = (text or "").replace(",", "").strip()
    if not s:
        return None
    try:
        return cast(s)
    except ValueError:
        return None


def parse_items(xml_text: str) -> list:
    """RTMS 상업업무용 응답 XML → 행 리스트. 정규식이 아니라 ET로 판다.

    **한 행도 버리지 않는다.** 해제(cdealType)도 남기고 canceled 플래그만 세우며, 금액·면적이
    깨진 행은 parse_error를 달아 돌려준다(거르는 판단은 build_trades가 한다). 응답의 미해제
    표시는 빈 문자열이 아니라 공백 1칸이라 strip 없이 bool을 재면 전 행이 '해제'가 된다.
    """
    root = ET.fromstring(xml_text)
    out = []
    for el in root.findall("./body/items/item"):
        def g(tag):
            return (el.findtext(tag) or "").strip()

        amount_man = _num(g("dealAmount"), int)          # 응답 단위는 만원, 콤마 포함
        area = _num(g("buildingAr"), float)
        y, m, d = (_num(g("dealYear"), int), _num(g("dealMonth"), int), _num(g("dealDay"), int))
        ymd = f"{y:04d}-{m:02d}-{d:02d}" if None not in (y, m, d) else ""
        won = amount_man * 10_000 if amount_man is not None else 0
        row = {
            "sgg_cd": g("sggCd"), "umd": g("umdNm"), "jibun_masked": g("jibun"),
            "use": g("buildingUse") or "미상",
            "building_type": g("buildingType") or "미상",   # 일반(단독 건물) vs 집합(구분 소유)
            "deal_ymd": ymd,
            "amount_won": won,
            "building_ar_m2": area if area is not None else 0.0,
            "plottage_ar_m2": _num(g("plottageAr"), float),
            "floor": _num(g("floor"), int),
            "build_year": _num(g("buildYear"), int),
            "per_m2_won": round(won / area) if (area and area > 0 and won) else 0,
            "dealing_gbn": g("dealingGbn") or "미상",
            "sler": g("slerGbn") or "미상",
            "buyer": g("buyerGbn") or "미상",
            "canceled": bool(g("cdealType")),
            "share_deal": bool(g("shareDealingType")),
        }
        bad = []
        if amount_man is None:
            bad.append(f"금액 파싱 실패({g('dealAmount')!r})")
        if area is None or area <= 0:
            bad.append(f"건물면적 파싱 실패({g('buildingAr')!r})")
        if not ymd:
            bad.append(f"거래일 파싱 실패({g('dealYear')!r}-{g('dealMonth')!r}-{g('dealDay')!r})")
        if bad:
            row["parse_error"] = " · ".join(bad)
        out.append(row)
    return out


def jibun_match(masked: str, full: str) -> bool:
    """마스킹된 지번('7*')이 시드의 실지번('737')을 가리킬 수 있는가.

    `*`는 가려진 자리이므로 `.*`로 풀어 fullmatch한다. 다만 **숫자가 한 자도 남지 않은
    지번('*')은 아무것도 가리키지 않는다** — 그걸 매칭시키면 그 법정동의 아무 거래나 시드
    건물에 붙는다. 정보량이 0인 값은 매칭 실패로 답한다.
    """
    masked, full = (masked or "").strip(), (full or "").strip()
    if not masked or not full or not masked.strip("*"):
        return False
    return re.fullmatch(re.escape(masked).replace(r"\*", ".*"), full) is not None


def match_building(row: dict, seeds: list) -> dict | None:
    """실거래 한 행 → 시드 건물 매칭. 같은 시군구·법정동 + 지번 일치. 후보가 없으면 None.

    **후보가 여럿이면 `building_id`는 null이다.** 마스킹된 지번은 한 동을 특정하지 못한다 —
    서초동 `1***`는 시드 여러 동에 동시에 걸린다. 예전에는 시드 파일 순서의 첫 후보를 골라
    돌려줬는데, 그러면 소비자가 building_id로 groupby만 해도 1,600행이 엉뚱한 한 동에 몰린다.
    고르지 못하는 자리에서는 고르지 않는다 — 후보 목록만 넘기고 판단을 소비자에게 넘긴다.

    seeds는 seed_buildings.json 행이거나 buildings.json 행이다. 후자는 `ledger`를 달고 오는데
    **대장 미승인 상태에서는 그 값이 null이다.** 그래서 ledger를 짚기 전에 반드시 존재를
    확인한다(`r["ledger"]["totArea"]`는 지금 TypeError로 죽는 코드다).
      - 동이 특정되고 연면적을 알 수 있으면 거래면적/연면적으로 whole(≥0.8)·partial을 가른다.
      - 아니면 area_ratio=None, kind="jibun_only" — 대장이 열린 뒤 재실행하면 승격된다.
    """
    masked = (row.get("jibun_masked") or "").strip()
    cands = [s for s in seeds
             if s.get("umd") == row.get("umd") and s.get("sgg_cd") == row.get("sgg_cd")
             and jibun_match(masked, s.get("jibun") or "")]
    if not cands:
        return None
    # 마스킹 없이 지번이 그대로 일치하는 시드가 하나면 그것이 답이다. 후보가 하나뿐이어도 답이다.
    # 그 밖(후보 복수·정확 일치 복수)은 특정 실패로 남긴다.
    exact = [s for s in cands if (s.get("jibun") or "").strip() == masked]
    chosen = exact[0] if len(exact) == 1 else (cands[0] if len(cands) == 1 else None)

    tot = ((chosen or {}).get("ledger") or {}).get("totArea") or 0.0
    area = row.get("building_ar_m2") or 0.0
    if chosen is not None and tot > 0 and area > 0:
        ratio = area / tot
        kind = "whole" if ratio >= WHOLE_RATIO else "partial"
        ratio = round(ratio, 6)
    else:
        ratio, kind = None, "jibun_only"
    return {"building_id": (chosen["id"] if chosen else None), "kind": kind, "area_ratio": ratio,
            "masked": "*" in masked, "candidates": [s["id"] for s in cands]}


def build_trades(rows: list, seeds: list):
    """파싱된 행 → (업무 행 + 매칭, 제외 집계). 제외는 세어서 신고하고 조용히 버리지 않는다.

    trades에는 업무 행만 남는다. 근생·판매 등은 raw 캐시에 그대로 있으므로 나중에 다른
    질문(가로상권 등)이 생기면 재수집 없이 다시 만들 수 있다.
    """
    trades, excl = [], {"price_gate": 0, "parse": 0}
    for r in rows:
        if r.get("parse_error"):
            excl["parse"] += 1
            continue
        if r.get("use") != OFFICE_USE:
            continue
        if not (GATE[0] <= (r.get("per_m2_won") or 0) <= GATE[1]):
            excl["price_gate"] += 1
            continue
        trades.append({**r, "match": match_building(r, seeds)})
    return trades, excl


def build_year_conflicts(trades: list) -> dict:
    """한 시드에 붙은 거래의 건축년도가 갈리는 곳 → {시드 id: [연도...]}. **매칭 오염의 증거다.**

    한 건물의 거래는 건축년도가 하나여야 한다. 여러 해가 섞였다면 둘 중 하나다.
      - 마스킹된 지번(`1**`)이 같은 법정동의 **다른 건물**을 끌어왔다(대부분 이쪽이다), 또는
      - 그 자리에서 옛 건물을 헐고 다시 지었다(콘코디언처럼 준공 전 거래가 섞인다).
    어느 쪽이든 그 시드의 매칭은 그대로 쓰면 안 된다. 이 함수는 세어 신고할 뿐 고르지 않는다 —
    가르려면 대장 사용승인일이 필요하고, 그전까지는 사람이 build_year를 보고 판단해야 한다.
    후보를 특정하지 못한 행(building_id=null)은 애초에 어느 시드의 것도 아니므로 세지 않는다.
    """
    years = {}
    for t in trades:
        bid = (t.get("match") or {}).get("building_id")
        if bid and t.get("build_year"):
            years.setdefault(bid, set()).add(t["build_year"])
    return {b: sorted(ys) for b, ys in sorted(years.items()) if len(ys) > 1}


def load_seeds() -> tuple:
    """매칭에 쓸 시드 목록과 대장 상태. buildings.json이 있으면 그쪽(ledger 포함)을 쓴다.

    반환 (seeds, ledger_ready). ledger_ready는 **ledger가 실제로 채워진 행이 하나라도 있는가**다
    — 파일 존재만으로 판정하면 지금처럼 전 행이 null인 제3상태를 놓친다.
    """
    if BUILDINGS_PATH.exists():
        seeds = json.loads(BUILDINGS_PATH.read_text(encoding="utf-8"))["buildings"]
        ready = any((s.get("ledger") or {}).get("totArea") for s in seeds)
        return seeds, ready
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))["buildings"], False


# ── 캐시·호출 ────────────────────────────────────────────────────────────────

def _page_no(path: Path) -> int:
    m = re.search(r"_p(\d+)\.xml$", path.name)
    return int(m.group(1)) if m else 0


def _cell_texts(sgg: str, ym: str, base: Path = None) -> list:
    """한 셀(시군구×월)의 캐시된 페이지 원문 목록(페이지 순)."""
    base = base or RAW_DIR
    return [p.read_text(encoding="utf-8")
            for p in sorted(base.glob(f"nrg_{sgg}_{ym}_p*.xml"), key=_page_no)]


def _pages_complete(texts: list) -> bool:
    """받아 둔 페이지가 totalCount를 채우는가. 절단본을 완결로 착각하지 않으려는 검사다.

    `>=`인 이유: 페이지를 넘기는 중에 원본이 갱신되면 나중 페이지의 totalCount가 앞 페이지보다
    작아져 받은 행이 총수를 넘을 수 있다. 그건 절단이 아니다. 부족한 경우(got < total)만 막는다.
    """
    if not texts:
        return False
    try:
        total = int(ET.fromstring(texts[0]).findtext("./body/totalCount") or -1)
        got = sum(len(ET.fromstring(t).findall("./body/items/item")) for t in texts)
    except (ET.ParseError, ValueError):
        return False
    return total >= 0 and got >= total


def copy_from_suji(sgg: str, ym: str) -> bool:
    """같은 셀이 수지 프로젝트 캐시에 있으면 복사해 온다(호출 절약). 완결본만 받는다."""
    pages = sorted(SUJI_RAW.glob(f"nrg_{sgg}_{ym}_p*.xml"), key=_page_no)
    if not pages or not _pages_complete([p.read_text(encoding="utf-8") for p in pages]):
        return False
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for p in pages:
        shutil.copy2(p, RAW_DIR / p.name)
    return True


def _fetch_page(sgg: str, ym: str, page: int, key: str):
    """한 페이지 원문. (text, err) — err: None|'quota'|'denied'|'nodata'|'transient'.

    캐시가 있으면 호출하지 않고, 정상 응답만 캐시한다.
    """
    cache = RAW_DIR / f"nrg_{sgg}_{ym}_p{page}.xml"
    if cache.exists():
        return cache.read_text(encoding="utf-8"), None
    params = {"LAWD_CD": sgg, "DEAL_YMD": ym, "pageNo": str(page),
              "numOfRows": str(PER_PAGE), "serviceKey": key}
    status, text = call_with_backoff(
        lambda: api_get(URL, params, timeout=TIMEOUT, retries=1), tries=3)
    time.sleep(CALL_GAP)
    # **상태 코드보다 봉투를 먼저 읽는다.** 이 게이트웨이는 쿼터 소진을 200으로도 보내지만
    # 429·5xx에 실어 보내기도 한다. 상태 코드부터 갈라 버리면 그런 응답이 '일시 오류'로 분류돼
    # 남은 1,200셀을 백오프까지 곁들여 계속 두드린다(G2B에서 일 쿼터를 90분에 태운 그 경로다).
    # api_get은 HTTPError 본문도 그대로 돌려주므로 비-200에도 봉투가 들어 있다.
    env = envelope_error(text)
    if env:
        return "", classify_envelope(*env)
    if status in (401, 403):
        return "", "denied"
    if status != 200:
        return "", "transient"
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return "", "transient"
    rc = (root.findtext("./header/resultCode") or "").strip()
    if rc not in ("00", "000"):
        kind = classify_envelope(rc, (root.findtext("./header/resultMsg") or "").strip())
        return "", (kind if kind != "unknown" else "transient")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(text, encoding="utf-8")
    return text, None


def fetch_cell(sgg: str, ym: str, key: str):
    """한 셀의 전 페이지. (페이지 원문들, err, 호출수). err가 있으면 그 셀은 미완이다."""
    texts, calls, page = [], 0, 1
    while True:
        cached = (RAW_DIR / f"nrg_{sgg}_{ym}_p{page}.xml").exists()
        text, err = _fetch_page(sgg, ym, page, key)
        if err:
            return texts, err, calls
        calls += 0 if cached else 1
        texts.append(text)
        root = ET.fromstring(text)
        total = int(root.findtext("./body/totalCount") or "0")
        got = sum(len(ET.fromstring(t).findall("./body/items/item")) for t in texts)
        if got >= total or not root.findall("./body/items/item"):
            return texts, None, calls
        page += 1


# ── 수집 ────────────────────────────────────────────────────────────────────

def prior_cells() -> int:
    """이미 저장돼 있는 산출이 담고 있는 셀 수. 파일이 없거나 못 읽으면 0."""
    try:
        return int(json.loads(OUT_PATH.read_text(encoding="utf-8"))["meta"]["cells_done"])
    except Exception:
        return 0


def save_result(result: dict, done: set) -> Path:
    """산출을 쓴다. **이번 실행이 기존 산출보다 얇으면 덮어쓰지 않고 .partial 로 비켜 쓴다.**

    raw 캐시는 용량 때문에 커밋하지 않고 산출 JSON만 커밋한다. 그래서 저장소를 새로 clone한
    곳에서는 캐시가 비어 있는 게 정상이고, 거기서 수집기를 돌리면 첫 실행은 쿼터·시간 때문에
    반드시 일부만 받는다. 그 결과로 1,235셀짜리 산출을 600셀짜리로 — 최악은 0셀로 — 덮어쓰면
    커밋된 데이터가 조용히 사라진다. 키 권한이 없어 denied로 끝나는 실행, `--limit` 시험 실행도
    같은 모양이다. 그래서 판정은 '이번에 담은 셀 수'와 '이미 담겨 있던 셀 수'의 비교로 한다.
      - 이번이 더 얇다 → .partial (기존 산출·진행 파일은 손대지 않는다)
      - 중단(quota/denied)됐는데 나아진 것도 없다 → .partial
      - 그 밖(처음 만드는 산출 포함) → 정상 저장
    이어받기는 진행 파일이 아니라 raw 캐시가 근거이므로, .partial로 비켜 써도 다음 실행은
    중단 지점부터 그대로 잇는다.
    """
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    prior, built = prior_cells(), result["meta"]["cells_done"]
    thinner = built < prior
    stalled = bool(result["meta"]["stopped"]) and built <= prior
    if thinner or stalled:
        result["meta"]["written_to"] = PARTIAL_PATH.name
        result["meta"]["partial_write_reason"] = (
            f"이번 실행은 {built}셀만 담았고 기존 산출은 {prior}셀이라 덮어쓰지 않았다"
            f"{' (중단: ' + result['meta']['stopped'] + ')' if result['meta']['stopped'] else ''}. "
            f"다시 실행하면 raw 캐시를 이어받아 채운다.")
        PARTIAL_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        return PARTIAL_PATH
    result["meta"]["written_to"] = OUT_PATH.name
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    write_progress(done)
    return OUT_PATH


def write_progress(done: set):
    """진행 파일 기록. 기존 기록보다 줄어드는 쓰기는 하지 않는다(캐시 없는 clone 보호)."""
    try:
        before = len(json.loads(PROG_PATH.read_text(encoding="utf-8"))["done"])
    except Exception:
        before = 0
    if len(done) < before:
        return
    PROG_PATH.write_text(json.dumps({"done": sorted(done)}, ensure_ascii=False, indent=1),
                         encoding="utf-8")


def build_from_cache(months: list, seeds: list) -> tuple:
    """캐시에 있는 완결 셀 전부를 다시 읽어 trades를 만든다. API를 부르지 않는다."""
    trades, excl = [], {"price_gate": 0, "parse": 0}
    n_all, cells, truncated = 0, [], []
    for sgg in SGG_LIST:
        for ym in months:
            texts = _cell_texts(sgg, ym)
            if not texts:
                continue
            if not _pages_complete(texts):
                truncated.append(f"{sgg}_{ym}")   # 절단본은 쓰지 않는다 — 다음 실행이 마저 받는다
                continue
            rows = [r for t in texts for r in parse_items(t)]
            n_all += len(rows)
            part, part_excl = build_trades(rows, seeds)
            trades.extend(part)
            for k in excl:
                excl[k] += part_excl[k]
            cells.append(f"{sgg}_{ym}")
    trades.sort(key=lambda r: (r["deal_ymd"], r["sgg_cd"], r["umd"], r["jibun_masked"]))
    return trades, excl, n_all, cells, truncated


def collect(limit: int = None, rebuild: bool = False) -> dict:
    """5개 구 × 2006-01~현재를 재개형으로 수집하고, 캐시 전량에서 trades.json을 다시 만든다."""
    months = month_range()
    seeds, ledger_ready = load_seeds()
    cells = [(sgg, ym) for sgg in SGG_LIST for ym in months]
    # 무엇을 이미 받았는지는 **진행 파일이 아니라 캐시에게 묻는다.** 진행 파일은 저장소에 커밋되지만
    # raw 캐시는 용량 때문에 커밋되지 않는다(.gitignore). 저장소를 새로 clone한 사람이 진행 파일을
    # 믿으면 "1,235셀 전부 완료"라고 읽고 한 번도 호출하지 않은 채 **빈 trades.json으로 덮어쓴다.**
    # 그래서 진행 파일은 결과의 사본일 뿐이고, 판단 근거는 디스크에 실제로 있는 완결 셀이다.
    done = {f"{s}_{y}" for s, y in cells if _pages_complete(_cell_texts(s, y))}
    stop, failed, calls, copied, saved_at, streak = "", [], 0, 0, 0, 0

    if not rebuild:
        key = load_config()["service_key"]
        # 최근 월부터, 한 달 안에서는 5개 구를 나란히 받는다. 이 수집은 쿼터·시간 때문에 여러 날에
        # 걸쳐 이어지므로 중간 산출물이 늘 쓸 만해야 한다 — 구 순서대로 받으면 중단 시점의
        # trades.json이 '종로만 20년'처럼 반쪽이 되고, 최근 월부터 받으면 '5개 구 최근 N개월'이 된다.
        # 언더라이팅이 먼저 보는 것도 최근 거래다.
        todo = sorted((c for c in cells if f"{c[0]}_{c[1]}" not in done),
                      key=lambda c: (c[1], c[0]), reverse=True)
        if limit:
            todo = todo[:limit]
        print(f"대상 {len(cells)}셀 중 미완 {len(todo)}셀 ({SGG_LIST[0]}~{SGG_LIST[-1]}, "
              f"{months[0]}~{months[-1]})", flush=True)
        for sgg, ym in todo:
            cell = f"{sgg}_{ym}"
            if copy_from_suji(sgg, ym):                    # 남의 캐시로 때울 수 있으면 호출하지 않는다
                done.add(cell)
                copied += 1
                continue
            texts, err, n = fetch_cell(sgg, ym, key)
            calls += n
            if err in ("quota", "denied"):
                # 서킷브레이커. 한 셀에서 소진을 확인했으면 남은 셀을 두드려 봐야 같은 답이고
                # 다음 날 몫만 태운다. 여기서 멈추고 저장한다.
                stop = err
                break
            if err:
                failed.append({"cell": cell, "reason": err})
                streak += 1
                if streak >= MAX_FAIL_STREAK:
                    # 열 셀이 내리 실패하면 이 서버는 지금 대답할 상태가 아니다. 1,200셀을 끝까지
                    # 두드려 실패 목록만 부풀리느니 물러난다 — 다음 실행이 이어받는다.
                    stop = "fail_streak"
                    break
                continue
            streak = 0
            done.add(cell)
            # 한 셀이 여러 페이지를 쓰면 호출 수가 건너뛰므로 나머지 연산으로 재면 저장이 통째로
            # 빠질 수 있다. 마지막 저장 시점과의 차이로 잰다.
            if calls - saved_at >= SAVE_EVERY:
                saved_at = calls
                write_progress(done)
                print(f"  {calls}호출 · 최근 {cell}: {len(texts)}페이지", flush=True)

    trades, excl, n_all, built_cells, truncated = build_from_cache(months, seeds)
    matched = [t for t in trades if t["match"]]
    kinds = {k: sum(1 for t in matched if t["match"]["kind"] == k)
             for k in ("whole", "partial", "jibun_only")}
    result = {
        "trades": trades,
        "meta": {
            "months": f"{months[0]}~{months[-1]}",
            "sgg_list": SGG_LIST,
            "n_office": len(trades),
            "n_all": n_all,
            "excluded": excl,
            "gate_won_per_m2": list(GATE),
            "cells_done": len(built_cells),
            "cells_total": len(cells),
            "cells_truncated": truncated,
            "failed_cells": failed,
            "api_calls": calls,
            "cells_from_suji_cache": copied,
            "matched": len(matched),                 # 시드 후보가 하나라도 잡힌 행
            "match_kinds": kinds,
            # 동이 특정된 행(building_id != null)과 특정 실패로 남긴 행. 앞의 것만 쓸 수 있다.
            "match_resolved": sum(1 for t in matched if t["match"]["building_id"]),
            "match_ambiguous": sum(1 for t in matched if not t["match"]["building_id"]),
            # 마스킹이 없고 후보도 하나뿐인 행 — 지금 필지 수준에서 가장 믿을 만한 부분집합이다.
            "match_exact": sum(1 for t in matched
                               if not t["match"]["masked"] and len(t["match"]["candidates"]) == 1),
            "match_build_year_conflicts": build_year_conflicts(trades),
            "canceled": sum(1 for t in trades if t["canceled"]),
            "ledger_ready": ledger_ready,
            "stopped": stop,
            "complete": not stop and len(built_cells) == len(cells) and not failed,
            "collected_at": datetime.date.today().isoformat(),
            "source": "국토부 RTMS 상업업무용",
            "note": ("trades는 buildingUse가 '업무'인 행만 담는다(그 외 용도는 raw 캐시에만 있다). "
                     "해제(cdealType) 행은 지우지 않고 canceled=true로 남긴다 — 취소된 계약도 "
                     "그 시점의 호가 정보다. **match.building_id가 null이면 마스킹된 지번이 여러 "
                     "시드에 동시에 걸려 동을 특정하지 못한 행이다** — candidates에 후보를 다 적어 "
                     "두었으니 소비자가 판단해야 하고, 첫 후보를 고르는 식의 처리는 금물이다. "
                     "ledger_ready가 false면 연면적을 몰라 kind는 전부 jibun_only이며, 대장이 열린 "
                     "뒤 재실행하면 수집 없이 whole/partial로 승격된다. match_build_year_conflicts에 "
                     "오른 시드는 붙은 거래의 건축년도가 갈린다는 뜻이라 매칭이 오염됐다는 증거다 "
                     "— 마스킹 지번이 같은 법정동의 다른 건물을 끌어왔거나, 그 자리를 헐고 다시 "
                     "지은 것이다. 어느 쪽이든 그 시드 매칭은 build_year로 갈라 보기 전엔 못 쓴다."),
        },
    }
    # 진행 파일에는 **실제로 산출에 쓰인 셀**만 적는다. done은 이번 실행이 받았다고 믿는 집합이고
    # built_cells는 캐시가 증명한 집합이라, 둘이 어긋나면 증명된 쪽을 남긴다.
    save_result(result, set(built_cells))
    return result


def main():
    rebuild = "--rebuild" in sys.argv
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    print(f"RTMS 상업업무용 실거래 수집({'캐시 재구성' if rebuild else '수집'}): "
          f"{' '.join(SEOUL_GU[s] for s in SGG_LIST)}")
    meta = collect(limit=limit, rebuild=rebuild)["meta"]
    print(f"\n  셀 {meta['cells_done']}/{meta['cells_total']} · 전 용도 {meta['n_all']:,}행 → "
          f"업무 {meta['n_office']:,}행(해제 {meta['canceled']}건) · API {meta['api_calls']}회 "
          f"· 수지 캐시 재사용 {meta['cells_from_suji_cache']}셀")
    print(f"  제외: 게이트 밖 {meta['excluded']['price_gate']}행 · 파싱 실패 "
          f"{meta['excluded']['parse']}행 (게이트 {GATE[0]:,}~{GATE[1]:,}원/㎡)")
    print(f"  시드 후보 잡힌 행 {meta['matched']} → 동 특정 {meta['match_resolved']}행"
          f"(마스킹 없는 단독 {meta['match_exact']}행) · 특정 실패 {meta['match_ambiguous']}행은 "
          f"building_id=null · {meta['match_kinds']} · 대장 준비 {meta['ledger_ready']}")
    conflicts = meta["match_build_year_conflicts"]
    if conflicts:
        print(f"  ⚠ 건축년도가 갈리는 시드 {len(conflicts)}곳 — 매칭 오염 증거(다른 건물이 섞였거나 "
              f"헐고 다시 지은 자리다): " + ", ".join(f"{b}{ys}" for b, ys in list(conflicts.items())[:4]))
    if meta["cells_truncated"]:
        print(f"  ⚠ 절단 셀 {len(meta['cells_truncated'])}개: {meta['cells_truncated'][:5]}")
    if meta["failed_cells"]:
        print(f"  ⚠ 실패 셀 {len(meta['failed_cells'])}개: {meta['failed_cells'][:5]}")
    if meta["stopped"]:
        reason = {"quota": " — 일일 쿼터 소진. 다음 실행이 이어받는다.",
                  "denied": " — 키 권한 문제. 활용신청 상태를 확인해야 한다.",
                  "fail_streak": f" — {MAX_FAIL_STREAK}셀 연속 실패. 서버 상태를 보고 다시 돌린다."}
        print(f"  ⚠ 중단 사유: {meta['stopped']}{reason.get(meta['stopped'], '')}")
    if meta.get("partial_write_reason"):
        print(f"  ⚠ 기존 산출을 지키려고 비켜 썼다: {meta['partial_write_reason']}")
    print(f"  저장: {ROOT / 'data' / meta['written_to']}")
    print("COMPLETE" if meta["complete"] else "RESUME_NEEDED")


if __name__ == "__main__":
    main()
