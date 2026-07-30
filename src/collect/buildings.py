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
BldRgstHubService 는 전 오퍼레이션이 HTTP 200 이 아닌 평문 403 Forbidden 이다. 같은
service_key로 RTMSDataSvcNrgTrade(200)·ArchPmsHubService(200)는 정상이고, 키를 망가뜨리면
401, 없는 오퍼레이션은 404가 온다. 그러므로 키도 경로도 유효한데 **이 키에 이 서비스
접근 권한이 없다**는 뜻이다 — data.go.kr 활용신청 미승인이 가장 유력하나, 평문 403은
게이트웨이 단 차단(IP·요금제 등)에서도 똑같이 나오므로 단정하지는 않는다.
(구 BldRgstService_v2 는 없는 서비스와 같은 500을 돌려준다 — 폐지된 것으로 보인다.)
그래서 collect()는 대장이 잠겨 있어도 VWorld 부분을 수집해 저장하고 마지막 줄에 RESUME_NEEDED
를 찍는다. 권한이 열린 뒤 다시 실행하면 캐시된 VWorld는 재호출 없이 통과하고 대장만 채운다.

쿼터 소진(봉투 22)도 같은 방식으로 저장까지 가고 RESUME_NEEDED 로 끝난다 — 실패가 아니라
다음 실행이 이어받을 일이다. 데이터 없음(봉투 03)만 건별 failed 로 남기고 계속한다.

**승인이 떨어진 뒤 해야 할 일은 docs/ledger-unlock-checklist.md 에 모아 두었다** — 이 독스트링의
403 절 정정, 연속 일시오류 서킷브레이커, 미상 봉투의 저장 없는 사망 경로, fixture 실응답 교체,
필지 공유 8동의 match_method 확인, mgmBldrgstPk 실태그명 확인, trades --rebuild 승격이 거기 있다.
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
from src.collect.common import (ROOT, SEOUL_GU, api_get, call_with_backoff,  # noqa: E402,F401
                                classify_envelope, envelope_error, load_config)

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
    """대장 API에 이 키의 접근 권한이 없다(401/403 또는 봉투 20·30·31·32). 전역 사유다."""


class LedgerQuotaExceeded(RuntimeError):
    """일일 호출 쿼터 소진(봉투 22). 전역 사유이되 실패가 아니다 — 저장하고 다음 실행이 이어받는다."""


class LedgerNoData(RuntimeError):
    """조회 결과 없음(봉투 03). 건별 사유다 — 그 건만 failed에 남기고 계속한다."""


class LedgerTransient(RuntimeError):
    """일시적 서버 사고(봉투 04·05·21). 재시도 후에도 안 되면 그 건만 격리하고 계속한다."""


# 봉투 해석(envelope_error·classify_envelope)은 common.py 단일 출처다 — 실거래 수집기와 공유한다.
# 여기서는 그 판정을 대장 수집기의 행동(예외 성격)으로만 옮긴다.


def _raise_for_envelope(code: str, msg: str, where: str):
    """오류 봉투를 성격별 예외로 올린다."""
    detail = f"{where}: 사유코드 {code or '?'} {msg or '(메시지 없음)'}"
    kind = classify_envelope(code, msg)
    if kind == "quota":
        raise LedgerQuotaExceeded(f"대장 API 일일 쿼터 소진 — {detail}")
    if kind == "denied":
        raise LedgerAccessDenied(f"대장 API 접근 권한 없음 — {detail}")
    if kind == "nodata":
        raise LedgerNoData(f"대장 조회 결과 없음 — {detail}")
    if kind == "transient":
        raise LedgerTransient(f"대장 API 일시 오류 — {detail}")
    raise RuntimeError(f"대장 API 오류 봉투(성격 미상) — {detail}")


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


def pick_main_with_method(items: list, seed: dict):
    """`pick_main_building`과 같되 (선택된 동, 선택 방법)을 함께 돌려준다.

    방법은 셋이다.
      `"alias"`          이름·별칭이 정확히 한 동에 걸렸다 — 가장 믿을 만하다.
      `"alias_fallback"` 이름이 여러 동에 걸려 그 부분집합 안에서 용도·연면적으로 좁혔다.
      `"fallback"`       이름이 아무 동에도 안 걸려 필지 전체에서 골랐다 — **믿을 수 없다.**
    필지를 공유하는 시드가 여럿일 때 `"fallback"`은 서로 같은 동을 집을 수 있으므로,
    호출자는 이 값을 행에 남겨 사람이 볼 수 있게 해야 한다.
    """
    if not items:
        return None, "none"
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
        if len(best[0]) == 1:
            return best[0][0], "alias"
        return _fallback(best[0]), "alias_fallback"
    if NOTE_BAN_AREA_MAX in (seed.get("note") or ""):
        return None, "none"  # 이름으로만 고르라고 못박은 필지 — 엉뚱한 동을 집느니 실패로 남긴다
    return _fallback(items), "fallback"


def pick_main_building(items: list, seed: dict):
    """한 필지의 여러 동 중 시드가 가리키는 본건물. 못 고르면 None.

    이름 매칭이 먼저다. 시드의 name·aliases 각각이 몇 동에 걸리는지 세어 **가장 적은 동에
    걸리는 키**(=필지 안에서 변별력이 가장 큰 키)를 채택한다. 단지명처럼 전 동에 걸리는
    alias는 이 규칙에서 자동으로 밀려난다. 그래도 여러 동이 남으면 그 안에서만 폴백한다.
    """
    return pick_main_with_method(items, seed)[0]


def duplicate_assignments(rows: list) -> dict:
    """두 시드가 같은 대장 동(`mgmBldrgstPk`)을 집었는지 찾는다 → {대장키: [시드 id, ...]}.

    IFC 3동·파크원 2동·마제스타시티 2동처럼 **한 지번을 여러 시드가 공유**하는 경우, 이름
    매칭이 실패하면 셋이 나란히 같은 폴백 동을 집는다. 그것도 조용히. 필지 단위로는 어떤
    검증도 이 사고를 잡지 못하므로 수집이 끝난 뒤 전체를 훑어 교차 검사한다.
    """
    seen = {}
    for row in rows:
        pk = (row.get("ledger") or {}).get("mgmBldrgstPk")
        if pk:
            seen.setdefault(pk, []).append(row["id"])
    return {pk: ids for pk, ids in seen.items() if len(ids) > 1}


def to_ledger(item: dict) -> dict:
    """표제부 item → 산출 스키마의 ledger 딕셔너리. parking은 기계식·자주식 4항목의 합."""
    return {
        # 대장 동의 고유키. 두 시드가 같은 동을 집는 사고를 잡는 유일한 근거라 반드시 보존한다.
        "mgmBldrgstPk": item.get("mgmBldrgstPk", ""),
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
    where = f"{sgg}/{bjdong}/{bun}-{ji} p{page}"
    status, text = -1, ""
    last_transient = None
    for attempt in range(EMPTY_RETRIES + 1):
        status, text = call_with_backoff(
            lambda: api_get(BASE, params, timeout=TIMEOUT, retries=1, headers=HDR), tries=3)
        time.sleep(CALL_GAP)
        if status in (401, 403):
            raise LedgerAccessDenied(
                f"건축물대장 표제부 HTTP {status} — 이 service_key에 BldRgstHubService 접근 "
                f"권한이 없다(응답: {text.strip()[:80]!r}). data.go.kr 활용신청 미승인이 가장 "
                f"유력하나, 평문 403은 게이트웨이 단 차단에서도 같게 나온다. {where}")
        if status == 200 and text:
            env = envelope_error(text)
            if env:
                # 일시 오류만 재시도한다. 권한·쿼터·데이터없음은 다시 물어도 같은 답이다.
                if classify_envelope(env[0], env[1]) != "transient":
                    _raise_for_envelope(env[0], env[1], where)
                last_transient = env
            elif "<resultCode>" in text:
                break
        time.sleep(2.0 * (attempt + 1))
    if not (status == 200 and text and "<resultCode>" in text):
        # 여기까지 왔으면 재시도를 다 쓴 일시적 사고다. 전역 사망시키지 않고 이 건만 격리한다.
        detail = (f"{where}: status={status} len={len(text or '')} "
                  f"body={text[:160]!r}" if not last_transient
                  else f"{where}: 사유코드 {last_transient[0]} {last_transient[1]}")
        raise LedgerTransient(f"대장 응답을 {EMPTY_RETRIES + 1}회 시도했으나 못 받았다 — {detail}")
    root = ET.fromstring(text)
    rc = (root.findtext("./header/resultCode") or "").strip()
    if rc not in ("00", "000"):
        # 정상 봉투 안의 오류코드도 같은 분류를 쓴다. 자릿수 정규화는 classify_envelope이
        # 하되 resultMsg를 먼저 보므로, 뜻이 갈리는 "030" 같은 코드에 끌려가지 않는다.
        _raise_for_envelope(rc, (root.findtext("./header/resultMsg") or "").strip(), where)
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

VWORLD_TRIES = 3          # 일시적 타임아웃·끊김 재시도 횟수


def _vworld_get(url: str, params: dict) -> dict:
    """VWorld 한 단계 호출. 일시적 네트워크 오류만 재시도한다.

    55동 × 4단계 = 220회를 도는 동안 한 번의 읽기 타임아웃이 전 실행을 죽이고 저장에도
    이르지 못하는 일이 실제로 났다(2026-07-30). 마지막 시도까지 실패하면 예외를 그대로
    올려 호출자가 그 건을 실패로 기록하게 한다 — 삼키지 않는다.
    """
    qs = urllib.parse.urlencode(params, safe="%(),:|")
    req = urllib.request.Request(f"{url}?{qs}", headers={"User-Agent": "cheungwi/0.1"})
    for attempt in range(VWORLD_TRIES):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except Exception:
            if attempt == VWORLD_TRIES - 1:
                raise
            time.sleep(2.0 * (attempt + 1))


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


def _vworld_complete(got: dict) -> bool:
    """캐시해도 좋을 만큼 온전한 결과인가.

    반쪽 결과를 캐시하면 "캐시가 있으면 호출하지 않는다" 규칙 탓에 영구히 반쪽으로 남는다.
    좌표·용도지역·공시지가가 모두 채워진 것만 박제한다.
    """
    return ("error" not in got and got.get("lat") is not None and got.get("lon") is not None
            and bool(got.get("zones")) and not got.get("land_price_error")
            and bool(got.get("land_price_won_m2")))


def _vworld_cached(key: str, seed: dict, pnu: str) -> dict:
    """건물 단위 VWorld 캐시. 입력이 바뀌었거나 결과가 반쪽이면 캐시를 쓰지 않는다.

    캐시 키를 시드 id 하나로 두면 시드의 도로명주소나 지번이 고쳐져도 옛 좌표·공시지가를
    그대로 돌려준다 — 조용히, 영원히. 그래서 조회에 쓴 입력을 캐시에 함께 적고 대조한다.
    """
    VWORLD_RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache = VWORLD_RAW_DIR / f"{seed['id']}.json"
    want = {"address_road": seed["address_road"], "pnu": pnu}
    if cache.exists():
        payload = json.loads(cache.read_text(encoding="utf-8"))
        if payload.get("input") == want:
            return payload["result"]
    try:
        got = vworld_lookup(key, seed["address_road"], pnu)
    except Exception as e:      # 한 건의 네트워크 실패가 55동 수집 전체를 죽이면 안 된다
        return {"error": f"{type(e).__name__}: {e}"[:120]}
    if _vworld_complete(got):
        cache.write_text(json.dumps({"input": want, "result": got}, ensure_ascii=False, indent=1),
                         encoding="utf-8")
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
        row["match_method"] = None        # alias | alias_fallback | fallback | none
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
            except (LedgerAccessDenied, LedgerQuotaExceeded) as e:
                # 둘 다 전역 사유라 이후 대장 호출을 생략한다. 쿼터는 실패가 아니라 '다음에 이어받기'다.
                ledger_blocked = str(e)
                row["flags"].append(f"대장 미조회: {ledger_blocked}")
            except LedgerNoData as e:
                reason = f"대장 데이터 없음: {e}"
                failed.append({"id": seed["id"], "reason": reason})
                row["flags"].append(reason)
            except LedgerTransient as e:
                # 서버 일시 사고 — 이 건만 비우고 계속한다. 다음 실행이 이 동만 다시 받는다.
                reason = f"대장 일시 오류(다음 실행에서 재시도): {e}"
                failed.append({"id": seed["id"], "reason": reason})
                row["flags"].append(reason)
            else:
                row["ledger_dong_count"] = len(items)
                main, how = pick_main_with_method(items, seed)
                row["match_method"] = how
                if main is None:
                    reason = (f"대장 {len(items)}건 중 본건물 선택 실패"
                              if items else "대장 0건(지번 오류 의심)")
                    failed.append({"id": seed["id"], "reason": reason,
                                   "candidates": [i.get("bldNm", "") for i in items][:10]})
                    row["flags"].append(reason)
                else:
                    row["ledger"] = to_ledger(main)
                    row["flags"] += physical_flags(row["ledger"])
                    if how == "fallback" and len(items) > 1:
                        row["flags"].append(
                            f"이름 매칭 없이 폴백 선택({len(items)}동 중 '{main.get('bldNm', '')}"
                            f"{(' ' + main['dongNm']) if main.get('dongNm') else ''}') — 시드 "
                            f"aliases에 이 필지에서 변별력 있는 이름을 넣어야 한다. 사람 확인 필요.")
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

    # 필지 단위 검증으로는 절대 잡히지 않는 사고 — 두 시드가 같은 대장 동을 집었는지 전수 대조한다.
    dupes = duplicate_assignments(rows)
    for pk, ids in dupes.items():
        for row in rows:
            if row["id"] in ids:
                row["flags"].append(
                    f"대장 동 중복 배정({pk}) — {', '.join(ids)}가 같은 동을 집었다. "
                    f"둘 중 하나 이상은 틀렸다. 시드 aliases로 동을 구분해야 한다.")

    result = {
        "buildings": rows,
        "meta": {
            "matched": matched,
            "failed": failed,
            "vworld_ok": vworld_ok,
            "total": len(seeds),
            "duplicate_ledger": dupes,
            "match_methods": {m: sum(1 for r in rows if r["match_method"] == m)
                              for m in ("alias", "alias_fallback", "fallback", "none")},
            "gate": {"min_floor_area_m2": MIN_FLOOR_AREA_M2, "max_floor_area_m2": MAX_FLOOR_AREA_M2,
                     "min_grnd_flr": MIN_GRND_FLR},
            "ledger_status": ledger_blocked or ("OK" if matched else "미조회"),
            "complete": (not ledger_blocked and not dupes
                         and matched == len(seeds) and vworld_ok == len(seeds)),
            "collected_at": datetime.date.today().isoformat(),
            "source": "국토부 건축물대장 표제부 + VWorld",
            "endpoints_used": [BASE, "https://api.vworld.kr/req/address",
                               "https://api.vworld.kr/req/data (LT_C_UQ111, LP_PA_CBND_BUBUN)",
                               "https://api.vworld.kr/ned/data/getIndvdLandPriceAttr"],
            "note": ("지번은 시드(도로명→지번으로 확정)가 단일 출처다. VWorld가 돌려준 필지 지번은 "
                     "vworld.jibun_check에 참고로만 두고 시드를 덮어쓰지 않는다. 필지 공유 건물은 "
                     "시드 name·aliases 중 변별력 있는 키로 동을 고르며, 이름이 안 걸리고 시드 note가 "
                     "연면적 최대 선택을 금지한 필지는 고르지 않고 failed에 남긴다. "
                     "match_method가 'fallback'인 행은 이름이 안 걸려 필지 전체에서 고른 것이라 "
                     "믿을 수 없고, duplicate_ledger는 두 시드가 같은 대장 동을 집은 사고다."),
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
    if meta["match_methods"]["fallback"]:
        weak = [r["id"] for r in result["buildings"] if r["match_method"] == "fallback"]
        print(f"  ⚠ 이름 매칭 없이 폴백으로 고른 동 {len(weak)}건: {', '.join(weak)}")
    for pk, ids in meta["duplicate_ledger"].items():
        print(f"  ⚠ 대장 동 중복 배정 {pk}: {', '.join(ids)}")
    if meta["ledger_status"] not in ("OK",):
        print(f"  ⚠ 대장 상태: {meta['ledger_status']}")
    print(f"  저장: {OUT_PATH}")
    print("COMPLETE" if meta["complete"] else "RESUME_NEEDED")


if __name__ == "__main__":
    main()
