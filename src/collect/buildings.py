"""건물 마스터 수집기 — 건축물대장 표제부(국토부 건축HUB) + VWorld(좌표·용도지역·공시지가).

실행: python3 src/collect/buildings.py
산출: data/buildings.json — 시드 55동 각각의 {대장 표제부 요약, VWorld 대상지 속성, 물리 게이트 flags}

── 두 원천의 역할 분담(섞으면 안 된다) ──────────────────────────────────────
대장(표제부)  연면적·층수·높이·사용승인일·주차대수 — 건물의 물리 실체.
VWorld       좌표·용도지역·PNU·개별공시지가 — 필지의 법·입지 속성.
**지번은 어느 쪽도 시드를 덮어쓰지 않는다.** Task 2가 도로명→지번 방향으로 55행을 확정했고,
VWorld POI의 지번은 건물관리번호에 박제된 구(舊)지번을 역산해 내놓는 일이 잦아 신뢰할 수 없다
(정비사업 합필지 8건 실측). 그래서 지오코딩도 지번이 아니라 **시드의 도로명주소**로 한다.
VWorld가 돌려준 필지 지번은 `vworld.jibun_check` 에 참고로만 적고, 시드와 다르면 flags에 남겨
사람이 대조하게 한다 — 자동 정정 금지.

── 한 필지에 여러 동이 설 때 본건물 고르기 ──────────────────────────────────
연면적 최대는 답이 아니다. 삼성동 159(아셈타워)는 코엑스·인터컨티넨탈과 필지를 공유해
연면적 최대를 고르면 코엑스가 잡힌다. 그래서 pick_main_building 은
  (1) 시드 name·aliases 중 **필지 안에서 변별력 있는 키**(가장 적은 동에 걸리는 키)로 먼저 매칭하고
  (2) 걸린 동이 여럿이거나 아무 키도 안 걸릴 때만 업무시설 우선 + 연면적 최대로 좁힌다.
  (3) 시드 note가 "연면적 최대 선택 금지"라고 못박았는데 이름이 안 걸리면 **고르지 않고 실패로 남긴다**.
'ASEM 및 한국종합무역센타단지' 같은 단지명 alias는 필지 안 모든 동에 걸려 변별력이 0이므로
(1)에서 자동으로 밀려나고 '아셈' 같은 키가 앞선다.

── 2026-07-30 현재 대장 API는 잠겨 있다 ────────────────────────────────────
BldRgstHubService 는 전 오퍼레이션이 HTTP 403 Forbidden 이다. 같은 service_key로
RTMSDataSvcNrgTrade(200)·ArchPmsHubService(200)는 정상이고, 키를 망가뜨리면 401, 없는
오퍼레이션은 404가 오므로 **키·경로 문제가 아니라 이 서비스에 활용신청이 안 된 것**이다
(구 BldRgstService_v2 는 없는 서비스와 같은 500을 돌려준다 — 폐지된 것으로 보인다).
그래서 collect()는 대장이 잠겨 있어도 VWorld 부분을 수집해 저장하고 마지막 줄에 RESUME_NEEDED
를 찍는다. 활용신청이 승인된 뒤 다시 실행하면 캐시된 VWorld는 재호출 없이 통과하고 대장만 채운다.
"""

import datetime
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

if __package__ in (None, ""):  # 스크립트로 직접 실행할 때만 저장소 루트를 경로에 올린다
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.collect.common import ROOT, SEOUL_GU, api_get, call_with_backoff, load_config  # noqa: E402

SEED_PATH = ROOT / "data" / "seed_buildings.json"
OUT_PATH = ROOT / "data" / "buildings.json"
RAW_DIR = ROOT / "data" / "raw" / "bldrgst"
VWORLD_RAW_DIR = ROOT / "data" / "raw" / "vworld"
LDONG_FILE = RAW_DIR / "ldong_full.txt"
LDONG_URL = ("https://gist.githubusercontent.com/FinanceData/"
             "4b0a6e1818cea9e77496e57b84bb4565/raw/b682e526c7e9ebd1c30f688b789aa018f396e1c9/"
             "%EB%B2%95%EC%A0%95%EB%8F%99%EC%BD%94%EB%93%9C%EC%A0%84%EC%B2%B4%EC%9E%90%EB%A3%8C.txt")

BASE = "https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo"
HDR = {"Accept": "*/*"}   # 건축HUB 공통 함정: Accept 없으면 200 + 빈 바디
TIMEOUT = 55              # 콜드 백엔드가 10초 넘게 끄는 일이 있다
PER_PAGE = 100
CALL_GAP = 0.3
EMPTY_RETRIES = 3         # 200 + 빈 바디는 콜드 백엔드 glitch → 재시도

VWORLD_GAP = 0.2          # 체인 단계 간 대기(429·쿼터 보호)
LAND_PRICE_YEAR = "2025"  # 개별공시지가 기준연도(2026년분은 5월 결정공시 이후 반영)

# 물리 게이트 — 프라임 오피스가 만족해야 할 상식 범위. 위반은 버리지 않고 flags에 남긴다.
MIN_FLOOR_AREA_M2 = 200
MAX_FLOOR_AREA_M2 = 6000
MIN_GRND_FLR = 10

# 본건물 폴백에서 우선하는 주용도(앞일수록 우선)
PURPOSE_PRIORITY = ("업무시설", "제2종근린생활시설", "제1종근린생활시설")
# 시드 note가 이 뜻을 담고 있으면 이름 매칭 실패 시 폴백을 쓰지 않는다
NOTE_BAN_AREA_MAX = "연면적 최대 선택 금지"

_FLOAT_FIELDS = ("platArea", "archArea", "totArea", "vlRatEstmTotArea", "vlRat", "bcRat",
                 "heit", "atchBldArea", "totDongTotArea")
_INT_FIELDS = ("grndFlrCnt", "ugrndFlrCnt", "hoCnt", "hhldCnt", "fmlyCnt", "bylotCnt",
               "atchBldCnt", "rideUseElvtCnt", "emgenUseElvtCnt",
               "indrMechUtcnt", "oudrMechUtcnt", "indrAutoUtcnt", "oudrAutoUtcnt")
_STR_FIELDS = ("platPlc", "newPlatPlc", "bldNm", "dongNm", "mainAtchGbCdNm", "regstrGbCdNm",
               "regstrKindCdNm", "mainPurpsCdNm", "etcPurps", "strctCdNm", "mgmBldrgstPk",
               "sigunguCd", "bjdongCd", "bun", "ji", "platGbCd",
               "pmsDay", "stcnsDay", "useAprDay", "crtnDay")
PARKING_FIELDS = ("indrMechUtcnt", "oudrMechUtcnt", "indrAutoUtcnt", "oudrAutoUtcnt")


class LedgerAccessDenied(RuntimeError):
    """대장 API가 서비스 단위로 잠겨 있다(401/403). 건별 실패가 아니라 전역 사유다."""


# ── 순수 함수 ────────────────────────────────────────────────────────────────

def bun_ji(jibun: str) -> tuple:
    """지번 문자열 → (본번4, 부번4). `"737"` → `("0737", "0000")`, `"60-1"` → `("0060", "0001")`."""
    if not re.fullmatch(r"\d+(-\d+)?", (jibun or "").strip()):
        raise ValueError(f"지번 형식이 아니다: {jibun!r}")
    bun, _, ji = jibun.strip().partition("-")
    return bun.zfill(4), (ji or "0").zfill(4)


def _num(text, cast, default):
    try:
        return cast(float((text or "").strip()))
    except (TypeError, ValueError):
        return default


def parse_title_items(xml_text: str) -> list:
    """표제부 응답 XML → item 딕셔너리 리스트. 숫자 필드는 float/int로 캐스팅한다.

    resultCode 검증은 호출자(_fetch_page)가 한다 — 이 함수는 잘 만들어진 XML만 받는다.
    """
    root = ET.fromstring(xml_text)
    out = []
    for el in root.findall("./body/items/item"):
        row = {f: (el.findtext(f) or "").strip() for f in _STR_FIELDS}
        row.update({f: _num(el.findtext(f), float, 0.0) for f in _FLOAT_FIELDS})
        row.update({f: _num(el.findtext(f), int, 0) for f in _INT_FIELDS})
        out.append(row)
    return out


def _norm(s: str) -> str:
    """이름 비교용 정규화: 공백·가운뎃점·하이픈 제거 후 소문자."""
    return re.sub(r"[\s·・\-_,.()]+", "", (s or "")).lower()


def _haystack(item: dict) -> str:
    return _norm(f"{item.get('bldNm', '')}{item.get('dongNm', '')}")


def _match_keys(seed: dict) -> list:
    keys = [seed.get("name", "")] + list(seed.get("aliases") or [])
    return [k for k in keys if _norm(k)]


def _fallback(items: list) -> dict:
    """업무시설 우선 + 연면적 최대. 주용도가 우선순위에 없으면 맨 뒤로 민다."""
    def rank(it):
        purps = it.get("mainPurpsCdNm", "")
        order = PURPOSE_PRIORITY.index(purps) if purps in PURPOSE_PRIORITY else len(PURPOSE_PRIORITY)
        return (order, -it.get("totArea", 0.0))
    return sorted(items, key=rank)[0]


def pick_main_building(items: list, seed: dict):
    """한 필지의 여러 동 중 시드가 가리키는 본건물. 못 고르면 None.

    이름 매칭이 먼저다. 시드의 name·aliases 각각이 몇 동에 걸리는지 세어 **가장 적은 동에
    걸리는 키**(=필지 안에서 변별력이 가장 큰 키)를 채택한다. 단지명처럼 전 동에 걸리는
    alias는 이 규칙에서 자동으로 밀려난다. 그래도 여러 동이 남으면 그 안에서만 폴백한다.
    """
    if not items:
        return None
    best = None  # (걸린 동 수, 키 순서) 가 가장 작은 후보
    for order, key in enumerate(_match_keys(seed)):
        # 포함 방향은 '키 ⊂ 대장 이름' 한쪽뿐이다. 반대 방향까지 허용하면 대장의 짧은 단지명이
        # 시드의 긴 키에 걸려 필지 안 모든 동이 매칭되고, 변별력 계산이 무너진다.
        nk = _norm(key)
        hit = [it for it in items if nk in _haystack(it)]
        if not hit:
            continue
        if best is None or (len(hit), order) < (len(best[0]), best[1]):
            best = (hit, order)
    if best is not None:
        return best[0][0] if len(best[0]) == 1 else _fallback(best[0])
    if NOTE_BAN_AREA_MAX in (seed.get("note") or ""):
        return None      # 이름으로만 고르라고 시드가 못박은 필지 — 엉뚱한 동을 집느니 실패로 남긴다
    return _fallback(items)


def to_ledger(item: dict) -> dict:
    """표제부 item → 산출 스키마의 ledger 딕셔너리. parking은 기계식·자주식 4항목의 합."""
    return {
        "bldNm": item.get("bldNm", ""),
        "dongNm": item.get("dongNm", ""),
        "totArea": item.get("totArea", 0.0),
        "archArea": item.get("archArea", 0.0),
        "platArea": item.get("platArea", 0.0),
        "grndFlrCnt": item.get("grndFlrCnt", 0),
        "ugrndFlrCnt": item.get("ugrndFlrCnt", 0),
        "heit": item.get("heit", 0.0),
        "useAprDay": item.get("useAprDay", ""),
        "mainPurpsCdNm": item.get("mainPurpsCdNm", ""),
        "etcPurps": item.get("etcPurps", ""),
        "vlRat": item.get("vlRat", 0.0),
        "bcRat": item.get("bcRat", 0.0),
        "parking": sum(item.get(f, 0) for f in PARKING_FIELDS),
        "hoCnt": item.get("hoCnt", 0),
    }


def physical_flags(ledger: dict) -> list:
    """저장 전 물리 게이트. 위반해도 행은 남기고 사유만 돌려준다(격리 원칙)."""
    flags = []
    floors = ledger.get("grndFlrCnt", 0) + ledger.get("ugrndFlrCnt", 0)
    tot = ledger.get("totArea", 0.0)
    if floors <= 0:
        flags.append("층당면적 이상(층수 0 — 연면적/층수를 계산할 수 없다)")
    else:
        per = tot / floors
        if not (MIN_FLOOR_AREA_M2 <= per <= MAX_FLOOR_AREA_M2):
            flags.append(f"층당면적 이상({per:,.0f}㎡/층, 허용 "
                         f"{MIN_FLOOR_AREA_M2:,}~{MAX_FLOOR_AREA_M2:,}㎡)")
    if ledger.get("grndFlrCnt", 0) < MIN_GRND_FLR:
        flags.append(f"층수 이상(프라임 기준 미달 — 지상 {ledger.get('grndFlrCnt', 0)}층)")
    apr = (ledger.get("useAprDay") or "").strip()
    if not (len(apr) == 8 and apr.isdigit()):
        flags.append(f"사용승인일 누락({apr or '공란'})")
    return flags


# ── 법정동코드 ───────────────────────────────────────────────────────────────

def _ensure_ldong() -> list:
    """법정동코드 전체자료(캐시)를 반환. 없으면 1회 다운로드."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if not LDONG_FILE.exists():
        req = urllib.request.Request(LDONG_URL, headers={"User-Agent": "cheungwi/0.1"})
        with urllib.request.urlopen(req, timeout=60) as r:
            LDONG_FILE.write_bytes(r.read())
    return LDONG_FILE.read_text(encoding="utf-8").splitlines()


def bjdong_index(ldong_lines: list) -> dict:
    """(시군구5, 법정동명) → 법정동 뒤 5자리. 폐지된 코드와 리(里)는 버린다.

    archub의 `_dong_codes`와 같은 기준으로 **동 단위**(뒤 5자리가 '00'으로 끝나는 코드)만 남긴다.
    리까지 넣으면 한 시군구 안에 같은 이름의 리가 둘 존재하는 일이 있어(예: 달성군 본리리 2곳)
    이름만으로는 코드를 정할 수 없다. 층위가 쓰는 서울 5개 구는 전부 동 단위다.
    같은 이름의 동이 한 구에 둘 이상 살아 있으면 기계가 고를 수 없으므로 예외를 던진다.
    """
    idx = {}
    for line in ldong_lines[1:]:
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        code, name, status = parts[0], parts[1], parts[2]
        if len(code) != 10 or status.strip() != "존재":
            continue
        if code[5:] == "00000" or not code.endswith("00"):
            continue
        key = (code[:5], name.split()[-1])
        if key in idx and idx[key] != code[5:]:
            raise RuntimeError(f"법정동 중복: {key} → {idx[key]}, {code[5:]}")
        idx[key] = code[5:]
    return idx


# ── 대장 조회 ────────────────────────────────────────────────────────────────

def _fetch_page(sgg: str, bjdong: str, bun: str, ji: str, page: int, key: str) -> str:
    """표제부 한 페이지 원문. 캐시가 있으면 호출하지 않는다. 정상 응답만 캐시한다."""
    cache = RAW_DIR / f"{sgg}_{bjdong}_{bun}_{ji}_p{page}.xml"
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    params = {"sigunguCd": sgg, "bjdongCd": bjdong, "platGbCd": "0", "bun": bun, "ji": ji,
              "numOfRows": str(PER_PAGE), "pageNo": str(page), "serviceKey": key}
    status, text = -1, ""
    for attempt in range(EMPTY_RETRIES + 1):
        status, text = call_with_backoff(
            lambda: api_get(BASE, params, timeout=TIMEOUT, retries=1, headers=HDR), tries=3)
        time.sleep(CALL_GAP)
        if status in (401, 403):
            raise LedgerAccessDenied(
                f"건축물대장 표제부 HTTP {status} — 이 service_key는 BldRgstHubService에 "
                f"활용신청이 되어 있지 않다(응답: {text.strip()[:80]!r}). "
                f"data.go.kr에서 활용신청·승인 후 다시 실행하라.")
        if status == 200 and text and "<resultCode>" in text:
            break
        time.sleep(2.0 * (attempt + 1))
    if not (status == 200 and text and "<resultCode>" in text):
        raise RuntimeError(f"대장 빈/이상 응답 {sgg}/{bjdong}/{bun}-{ji} p{page}: "
                           f"status={status} len={len(text or '')} body={text[:200]!r}")
    root = ET.fromstring(text)
    rc = root.findtext("./header/resultCode")
    if rc not in ("00", "000"):
        raise RuntimeError(f"대장 응답오류 {rc} {sgg}/{bjdong}/{bun}-{ji} p{page}: "
                           f"{root.findtext('./header/resultMsg')}")
    cache.write_text(text, encoding="utf-8")
    return text


def fetch_title_items(sgg: str, bjdong: str, bun: str, ji: str, key: str) -> list:
    """한 필지의 표제부 전 페이지 item. 페이지네이션이 끊기면 실패시킨다(절단본 박제 금지)."""
    text = _fetch_page(sgg, bjdong, bun, ji, 1, key)
    total = int(ET.fromstring(text).findtext("./body/totalCount") or "0")
    items = parse_title_items(text)
    page = 1
    while len(items) < total:
        page += 1
        more = parse_title_items(_fetch_page(sgg, bjdong, bun, ji, page, key))
        if not more:
            break
        items.extend(more)
    if len(items) != total:
        raise RuntimeError(f"{sgg}/{bjdong}/{bun}-{ji}: 페이지네이션 절단 — totalCount {total}인데 "
                           f"{len(items)}건만 받았다(마지막 응답 페이지 {page}).")
    return items


# ── VWorld 체인 ──────────────────────────────────────────────────────────────

def _vworld_get(url: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params, safe="%(),:|")
    req = urllib.request.Request(f"{url}?{qs}", headers={"User-Agent": "cheungwi/0.1"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def seed_pnu(sgg_cd: str, bjdong: str, jibun: str) -> str:
    """시드의 (시군구, 법정동, 지번) → PNU 19자리. 공시지가 조회의 기준은 이쪽이다.

    지오코딩 점이 떨어진 필지가 아니라 **시드가 확정한 대표지번**으로 필지를 지목한다.
    프라임 오피스는 여러 필지에 걸치는 일이 잦아, 도로명 점이 대표지번이 아닌 필지에 떨어지면
    엉뚱한 필지의 공시지가를 건물 값으로 박제하게 된다(실측 7동).
    """
    bun, ji = bun_ji(jibun)
    return f"{sgg_cd}{bjdong}1{bun}{ji}"


def vworld_lookup(key: str, address_road: str, pnu: str = "") -> dict:
    """도로명주소 → 좌표·용도지역, 그리고 시드 PNU → 개별공시지가.

    지번으로 지오코딩하지 않는다 — 시드의 도로명이 유일한 입력이다(구지번 오염 차단).
    좌표·용도지역은 도로명 점(건물 정문) 기준이고, PNU·공시지가는 시드 지번 기준이다.
    점이 떨어진 필지(`pnu_at_point`·`jibun_check`)는 사람 대조용 참고값이며 시드를 대체하지 않는다.
    """
    out = {"lat": None, "lon": None, "zones": [], "pnu": pnu,
           "land_price_won_m2": 0, "land_price_year": "",
           "pnu_at_point": "", "jibun_check": ""}
    geo = _vworld_get("https://api.vworld.kr/req/address", {
        "service": "address", "request": "getcoord", "version": "2.0", "crs": "EPSG:4326",
        "address": address_road, "refine": "true", "format": "json", "type": "road", "key": key})
    point = geo.get("response", {}).get("result", {}).get("point", {})
    if not point:
        out["error"] = f"지오코딩 실패({geo.get('response', {}).get('status')})"
        return out
    x, y = point["x"], point["y"]
    out["lon"], out["lat"] = round(float(x), 7), round(float(y), 7)
    time.sleep(VWORLD_GAP)

    zone = _vworld_get("https://api.vworld.kr/req/data", {
        "service": "data", "request": "GetFeature", "data": "LT_C_UQ111", "key": key,
        "geomFilter": f"POINT({x} {y})", "size": "5", "format": "json",
        "geometry": "false", "crs": "EPSG:4326"})
    feats = zone.get("response", {}).get("result", {}).get(
        "featureCollection", {}).get("features", [])
    out["zones"] = sorted({f.get("properties", {}).get("uname", "") for f in feats} - {""})
    time.sleep(VWORLD_GAP)

    parcel = _vworld_get("https://api.vworld.kr/req/data", {
        "service": "data", "request": "GetFeature", "data": "LP_PA_CBND_BUBUN", "key": key,
        "geomFilter": f"POINT({x} {y})", "size": "2", "format": "json",
        "geometry": "false", "crs": "EPSG:4326"})
    pfs = parcel.get("response", {}).get("result", {}).get(
        "featureCollection", {}).get("features", [])
    props = pfs[0].get("properties", {}) if pfs else {}
    out["pnu_at_point"] = props.get("pnu") or ""
    out["jibun_check"] = props.get("jibun") or props.get("addr") or ""
    time.sleep(VWORLD_GAP)

    if pnu:
        try:
            price = _vworld_get("https://api.vworld.kr/ned/data/getIndvdLandPriceAttr", {
                "key": key, "pnu": pnu, "stdrYear": LAND_PRICE_YEAR,
                "format": "json", "numOfRows": "3", "pageNo": "1"})
            rows = (price.get("indvdLandPrices") or {}).get("field") or []
            if rows:
                out["land_price_won_m2"] = int(rows[0].get("pblntfPclnd", 0) or 0)
                out["land_price_year"] = rows[0].get("stdrYear") or LAND_PRICE_YEAR
            else:
                # 시드 지번으로 만든 PNU에 공시지가가 없다 = 그 필지가 없을 수 있다는 신호다
                out["land_price_error"] = f"{LAND_PRICE_YEAR}년 공시지가 행 없음(PNU {pnu})"
        except Exception as e:  # 공시지가 실패는 치명이 아니다 — 사유만 남기고 진행
            out["land_price_error"] = f"{type(e).__name__}: {e}"[:120]
    else:
        out["land_price_error"] = "PNU 미확보로 공시지가 조회 생략"
    return out


def _vworld_cached(key: str, seed: dict, pnu: str) -> dict:
    """건물 단위 VWorld 캐시. 지오코딩 실패는 캐시하지 않는다(다음 실행이 다시 시도한다)."""
    VWORLD_RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache = VWORLD_RAW_DIR / f"{seed['id']}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    got = vworld_lookup(key, seed["address_road"], pnu)
    if "error" not in got:
        cache.write_text(json.dumps(got, ensure_ascii=False, indent=1), encoding="utf-8")
    return got


def pnu_parts(pnu: str):
    """PNU 19자리 → {"sgg_cd", "bjdong", "san", "jibun"}. 형식이 아니면 None.

    PNU = 법정동코드10 + 필지구분1(1 일반·2 산) + 본번4 + 부번4. 대조는 이 코드로 한다 —
    `jibun_check` 문자열은 "737 대"처럼 지목이 붙어 파싱이 흔들린다.
    """
    if not (len(pnu or "") == 19 and pnu.isdigit()):
        return None
    bun, ji = int(pnu[11:15]), int(pnu[15:19])
    return {"sgg_cd": pnu[:5], "bjdong": pnu[5:10], "san": pnu[10] == "2",
            "jibun": f"{bun}-{ji}" if ji else str(bun)}


# ── 수집 ────────────────────────────────────────────────────────────────────

def collect() -> dict:
    cfg = load_config()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    seeds = json.loads(SEED_PATH.read_text(encoding="utf-8"))["buildings"]
    bjdong = bjdong_index(_ensure_ldong())

    rows, failed = [], []
    ledger_blocked = ""      # 서비스 단위 차단 사유(한 번 걸리면 이후 대장 호출을 생략한다)
    matched = vworld_ok = 0
    for seed in seeds:
        assert seed["sgg_cd"] in SEOUL_GU, f"{seed['id']}: 서울 구가 아니다 {seed['sgg_cd']}"
        row = {k: seed[k] for k in ("id", "name", "region", "sgg_cd", "umd", "jibun")}
        row["ledger"] = None
        row["ledger_dong_count"] = None   # 이 필지의 표제부 동 수(본건물 선택의 난이도 지표)
        row["flags"] = []

        bj = bjdong.get((seed["sgg_cd"], seed["umd"]))
        bun, ji = bun_ji(seed["jibun"])
        if not bj:
            reason = f"법정동코드 미해석: {SEOUL_GU[seed['sgg_cd']]} {seed['umd']}"
            failed.append({"id": seed["id"], "reason": reason})
            row["flags"].append(reason)
        elif ledger_blocked:
            row["flags"].append(f"대장 미조회: {ledger_blocked}")
        else:
            try:
                items = fetch_title_items(seed["sgg_cd"], bj, bun, ji, cfg["service_key"])
            except LedgerAccessDenied as e:
                ledger_blocked = str(e)
                row["flags"].append(f"대장 미조회: {ledger_blocked}")
            else:
                row["ledger_dong_count"] = len(items)
                main = pick_main_building(items, seed)
                if main is None:
                    reason = (f"대장 {len(items)}건 중 본건물 선택 실패"
                              if items else "대장 0건(지번 오류 의심)")
                    failed.append({"id": seed["id"], "reason": reason,
                                   "candidates": [i.get("bldNm", "") for i in items][:10]})
                    row["flags"].append(reason)
                else:
                    row["ledger"] = to_ledger(main)
                    row["flags"] += physical_flags(row["ledger"])
                    matched += 1

        vw = _vworld_cached(cfg["vworld_key"], seed, seed_pnu(seed["sgg_cd"], bj, seed["jibun"])
                            if bj else "")
        if "error" in vw:
            row["flags"].append(f"VWorld: {vw['error']}")
        else:
            vworld_ok += 1
            # 도로명 점이 떨어진 필지를 시드와 대조한다 — 정정하지 않고 신고만 한다.
            # 여러 필지에 걸친 건물은 정문 점이 대표지번이 아닌 필지에 떨어지는 게 정상이다.
            at = pnu_parts(vw.get("pnu_at_point"))
            if at and (at["jibun"] != seed["jibun"] or at["sgg_cd"] != seed["sgg_cd"]
                       or (bj and at["bjdong"] != bj)):
                row["flags"].append(
                    f"도로명 점 필지 불일치(시드 {seed['umd']} {seed['jibun']} vs 점 "
                    f"{vw.get('jibun_check') or at['jibun']}) — 여러 필지에 걸친 건물이면 정상이다. "
                    f"공시지가·PNU는 시드 지번으로 조회했다. 사람 확인 권장.")
            if vw.get("land_price_error"):
                row["flags"].append(f"공시지가: {vw['land_price_error']}")
        row["vworld"] = vw
        rows.append(row)
        area = "-" if row["ledger"] is None else f"{row['ledger']['totArea']:,.0f}㎡"
        zones = "/".join(vw.get("zones") or []) or "-"
        price = vw.get("land_price_won_m2") or 0
        warn = f"  ⚠ {len(row['flags'])}건" if row["flags"] else ""
        print(f"  {seed['id']:<26} {seed['umd']} {seed['jibun']:<9} 대장={area} "
              f"용도지역={zones} 공시지가={price:,}원/㎡{warn}", flush=True)

    result = {
        "buildings": rows,
        "meta": {
            "matched": matched,
            "failed": failed,
            "vworld_ok": vworld_ok,
            "total": len(seeds),
            "gate": {"min_floor_area_m2": MIN_FLOOR_AREA_M2, "max_floor_area_m2": MAX_FLOOR_AREA_M2,
                     "min_grnd_flr": MIN_GRND_FLR},
            "ledger_status": ledger_blocked or ("OK" if matched else "미조회"),
            "complete": not ledger_blocked and matched == len(seeds),
            "collected_at": datetime.date.today().isoformat(),
            "source": "국토부 건축물대장 표제부 + VWorld",
            "endpoints_used": [BASE, "https://api.vworld.kr/req/address",
                               "https://api.vworld.kr/req/data (LT_C_UQ111, LP_PA_CBND_BUBUN)",
                               "https://api.vworld.kr/ned/data/getIndvdLandPriceAttr"],
            "note": ("지번은 시드(도로명→지번으로 확정)가 단일 출처다. VWorld가 돌려준 필지 지번은 "
                     "vworld.jibun_check에 참고로만 두고 시드를 덮어쓰지 않는다. 필지 공유 건물은 "
                     "시드 name·aliases 중 변별력 있는 키로 동을 고르며, 이름이 안 걸리고 시드 note가 "
                     "연면적 최대 선택을 금지한 필지는 고르지 않고 failed에 남긴다."),
        },
    }
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def main():
    print("건축물대장 표제부 + VWorld 건물 마스터 수집:")
    result = collect()
    meta = result["meta"]
    flagged = [r for r in result["buildings"] if r["flags"]]
    print(f"\n  대장 매칭 {meta['matched']}/{meta['total']}동 · VWorld {meta['vworld_ok']}/{meta['total']}동 "
          f"· 실패 {len(meta['failed'])}동 · flags {len(flagged)}동")
    for f in meta["failed"]:
        print(f"    실패 {f['id']}: {f['reason']}")
    if meta["ledger_status"] not in ("OK",):
        print(f"  ⚠ 대장 상태: {meta['ledger_status']}")
    print(f"  저장: {OUT_PATH}")
    print("COMPLETE" if meta["complete"] else "RESUME_NEEDED")


if __name__ == "__main__":
    main()
