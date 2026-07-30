"""DART 리츠 앵커 수집기: 서울 3대 권역 오피스를 보유한 상장리츠의 재무·배당.

실행: python3 src/collect/reits.py
산출: data/reits.json
  {"reits": {"293940": {"name": "신한알파리츠", "corp_code": "01276594", "holding": "mixed",
                        "office_assets": [{"building_id": "platinum-tower", "note": "..."}],
                        "fin": [{"year": 2025, "reprt": "11011", "assets": 0.0, "liab": 0.0,
                                 "equity": 0.0, "revenue": 0.0, "basis": "2025-12-31",
                                 "basis_raw": "2025.12.31 현재"}],
                        "div": [{"stlm_dt": "2025.12.31", "dps": 0.0, "total_div": 0.0, "yld": 0.0}]}},
   "meta": {...}}

층위에서 이 계열이 맡는 몫: 추정 NOI·자산가치의 **실측 앵커**다. 우리가 임대료·공실률에서
쌓아 올린 추정치는 검증할 방법이 없지만, 같은 건물을 실제로 보유한 리츠는 그 건물에서 나온
영업수익과 장부 자산·자본을 분기마다 공시한다. 시드(data/seed_reits.json)의 office_assets가
그 연결고리다 — 리츠 10종이 시드 55동 중 11동을 실제로 보유한다.

읽는 이가 반드시 알아야 할 한계 세 가지(수치를 그대로 NOI로 읽으면 틀린다):
  · **장부가다.** assets·equity는 취득원가 기준 장부금액이고 감정 NAV가 아니다.
  · **별도(OFS) 기준이다.** 자리츠·펀드를 통해 간접 보유하는 리츠(NH프라임·KB스타·대신밸류·
    디앤디플랫폼 등)의 별도 영업수익은 임대료가 아니라 배당·이자 수익 성격이다. 임대료 자체는
    자리츠 재무제표에 있다. 연결(CFS)을 섞지 않는 이유는 리츠마다 연결 범위가 달라 한 표에
    나란히 놓으면 비교가 무너지기 때문이다 — 대신 리츠마다 holding(direct·indirect·mixed)을
    실어 소비자가 산문을 읽지 않고도 가중치를 정할 수 있게 했다.
  · **분기 금액은 그 분기분이다.** fnlttSinglAcnt의 thstrm_amount는 해당 보고 기간의 값이고
    누적이 아니다. 리츠는 결산월이 제각각이라(삼성FN리츠는 사업연도가 3개월) 연 환산은
    bsns_year가 아니라 basis(재무상태표 기준일)와 결산기로 해야 한다.

수집 원칙(앞선 태스크에서 얻은 교훈):
  - status "000"만 캐시한다. "013"(자료 없음)은 아직 제출 전일 수 있어 박제하지 않는다.
  - 쿼터 소진·인증키 거부는 예외가 아니라 정상 종료 사유다. 받은 데까지 저장하고 멈춘다.
  - 이번 실행이 기존 산출보다 얇으면 덮어쓰지 않고 data/reits.partial.json 으로 비켜 쓴다.
  - corp_code는 corpCode.xml(zip)을 받아 **종목코드로** 매칭한다. 리츠 법인명은
    "○○위탁관리부동산투자회사"라 이름 검색이 불안정하다(순환 dart_corp.py의 교훈).
"""

import datetime
import io
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

if __package__ in (None, ""):  # 스크립트로 직접 실행할 때만 저장소 루트를 경로에 올린다
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.collect.common import ROOT, api_get, call_with_backoff, load_config  # noqa: E402

RAW_DIR = ROOT / "data" / "raw" / "dart"
SEED_PATH = ROOT / "data" / "seed_reits.json"
OUT_PATH = ROOT / "data" / "reits.json"
PARTIAL_PATH = ROOT / "data" / "reits.partial.json"  # 기존 산출보다 얇은 결과가 비켜 가는 자리
BASE = "https://opendart.fss.or.kr/api"

# 2020년부터 올해까지. 상수로 박으면 해가 바뀔 때 최신 분기가 조용히 빠지므로 오늘에서 끊는다.
YEARS = range(2020, datetime.date.today().year + 1)
REPRTS = ("11013", "11012", "11014", "11011")  # 1분기·반기·3분기·사업
CALL_GAP = 0.1
HOLDINGS = {"direct", "indirect", "mixed"}  # 별도 손익에 임대료가 잡히는가 배당이 잡히는가

# DART 응답 status. "000" 외에는 성격을 갈라 행동을 정한다.
OK, NODATA = "000", "013"
STOP_STATUS = {  # 더 두드려도 소용없는 상태 — 받은 데까지 저장하고 정상 종료한다
    "010": "등록되지 않은 인증키",
    "011": "사용할 수 없는 인증키(일시 사용 중지)",
    "012": "접근할 수 없는 IP",
    "020": "요청 제한 초과(일 20,000건)",
    "021": "조회 가능한 회사 개수 초과",
    "800": "시스템 점검 중",
}


class _Stop(Exception):
    """쿼터·인증키·점검처럼 이번 실행에서 더 진행할 수 없는 상태."""

    def __init__(self, status: str, message: str):
        super().__init__(f"{status} {STOP_STATUS.get(status, '')} — {message}")
        self.status, self.message = status, message


def _num(value):
    """콤마 낀 금액 문자열 → float. 빈 값·'-'·None 은 0.0 이 아니라 None(모름)이다."""
    try:
        return float(str(value).replace(",", ""))
    except (ValueError, TypeError):
        return None


def pick_revenue(rows: list[dict]) -> float | None:
    """fnlttSinglAcnt 응답 행에서 별도(OFS) 영업수익을 뽑는다. 없으면 None.

    리츠 손익계산서의 최상단 계정은 재무제표에서는 "영업수익"이지만, **주요계정 API가 실제로
    돌려주는 이름은 실측 10종 전부 "매출액"이다**(2026-07 캐시 86건에서 영업수익 0건·매출액 68건).
    그래서 실제로 값을 물어오는 경로는 매출액 쪽이고, 영업수익 우선순위는 계정명 표기가 바뀌거나
    다른 리츠가 편입될 때를 대비한 방어다(둘 다 있으면 영업수익).
    fs_div가 "CFS"(연결)인 행은 보지 않는다 — 연결 범위가 리츠마다 달라 섞으면 비교가 깨진다.
    """
    found: dict = {}
    for item in rows:
        if item.get("fs_div") != "OFS":
            continue
        name = (item.get("account_nm") or "").strip()
        if name in ("영업수익", "매출액") and name not in found:
            value = _num(item.get("thstrm_amount"))
            if value is not None:
                found[name] = value
    return found.get("영업수익", found.get("매출액"))


def _basis_date(raw: str) -> str:
    """재무상태표 기준일 원문("2025.11.30 현재") → ISO 날짜("2025-11-30").

    DART 는 이 값을 "YYYY.MM.DD 현재" 라는 산문으로 준다. 산출의 다른 날짜(collected_at·
    seed_as_of)는 전부 ISO 라, 시간축의 근거가 되는 이 필드만 표기가 달라지면 소비자가
    원천마다 파서를 따로 써야 한다. 그래서 basis 는 ISO 로 정규화하고 원문은 basis_raw 로
    남긴다 — DART 표기가 바뀌면 그 사실 자체가 증거이기 때문이다.
    빈 값은 빈 값 그대로 두되, 날짜로 읽히지 않는 값은 조용히 버리지 않고 멈춘다.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    m = re.match(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
    if not m:
        raise RuntimeError(f"재무상태표 기준일을 날짜로 읽지 못했다: {raw!r}")
    try:
        return datetime.date(*(int(x) for x in m.groups())).isoformat()
    except ValueError as e:
        raise RuntimeError(f"재무상태표 기준일이 달력에 없는 날짜다: {raw!r}") from e


def _mask(text: str, key: str) -> str:
    """오류 본문에 인증키가 섞여 나와도 로그·보고서에 남지 않게 가린다."""
    return text.replace(key, "***") if key else text


def _call(op: str, params: dict) -> dict:
    """OpenDART JSON 엔드포인트 한 번. HTTP 비정상·비JSON은 예외로 드러낸다(삼킴 금지)."""
    key = load_config()["dart_key"]
    status, text = call_with_backoff(
        lambda: api_get(f"{BASE}/{op}.json", {"crtfc_key": key, **params}, retries=1), tries=4)
    time.sleep(CALL_GAP)
    if status != 200:
        raise RuntimeError(f"DART HTTP {status} ({op} {params}): {_mask(text, key)[:400]}")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"DART 응답이 JSON이 아니다 ({op} {params}): "
                           f"{_mask(text, key)[:400]}") from e


def corp_index(tickers: list[str], rebuild: bool = False) -> dict:
    """corpCode.xml(zip) 전체를 받아 **종목코드로** corp_code를 찾는다.

    시드 종목이 하나라도 없으면 조용히 건너뛰지 않고 멈춘다 — 상장폐지·종목코드 변경을
    '수집 안 됨'으로 뭉개면 앵커가 소리 없이 비기 때문이다.
    rebuild=True 면 네트워크를 쓰지 않고 지난 실행이 남긴 매핑 사본만 읽는다.

    **같은 날 이미 받았으면 다시 받지 않는다.** corpCode.xml 은 상장법인 전체가 든 수 MB짜리
    zip 이라 매 실행 재다운로드는 DART 쿼터를 그냥 태운다. 하루 안에 상장코드가 바뀌는 일은
    실무상 없고, 날이 바뀌거나 사본에 없는 종목이 들어오면 그때 다시 받는다.
    """
    path = RAW_DIR / "corp_code_map.json"
    if not rebuild and path.exists():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            doc = {}
        cached = doc.get("map") or {}
        if (doc.get("fetched_at") == datetime.date.today().isoformat()
                and all(t in cached for t in tickers)):
            return {t: cached[t] for t in tickers}
    if rebuild:
        if not path.exists():
            raise RuntimeError(f"--rebuild 인데 {path} 가 없다. 먼저 네트워크로 한 번 수집하라.")
        cached = json.loads(path.read_text(encoding="utf-8"))["map"]
        missing = [t for t in tickers if t not in cached]
        if missing:
            raise RuntimeError(f"--rebuild: 매핑 사본에 없는 시드 종목코드 {missing}. "
                               f"네트워크 수집으로 사본을 갱신하라.")
        return {t: cached[t] for t in tickers}
    key = load_config()["dart_key"]
    req = urllib.request.Request(f"{BASE}/corpCode.xml?crtfc_key={key}",
                                 headers={"User-Agent": "cheungwi/0.1"})
    with urllib.request.urlopen(req, timeout=90) as r:
        raw = r.read()
    if raw[:2] != b"PK":  # 오류일 때는 zip 대신 status/message XML이 온다
        raise RuntimeError(f"corpCode.xml 이 zip 이 아니다: "
                           f"{_mask(raw[:400].decode('utf-8', 'replace'), key)}")
    zf = zipfile.ZipFile(io.BytesIO(raw))
    root = ET.fromstring(zf.read(zf.namelist()[0]).decode("utf-8"))
    listed = {}
    for el in root.iter("list"):
        stock = (el.findtext("stock_code") or "").strip()
        if stock:
            listed[stock] = {"corp_code": (el.findtext("corp_code") or "").strip(),
                             "dart_name": (el.findtext("corp_name") or "").strip()}
    hit = {t: listed[t] for t in tickers if t in listed}
    missing = [t for t in tickers if t not in listed]
    if missing:
        raise RuntimeError(f"corpCode.xml 에 없는 시드 종목코드 {missing} "
                           f"(DART 상장법인 {len(listed):,}건). 상장폐지·코드 변경을 확인하라.")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / "corp_code_map.json").write_text(
        json.dumps({"map": hit, "total_listed_in_dart": len(listed),
                    "fetched_at": datetime.date.today().isoformat()},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    return hit


def _fetch(corp: str, op: str, year: int, reprt: str, rebuild: bool = False):
    """(corp, op, 연도, 보고서) 한 칸. 성공 응답만 캐시하고, 자료 없음은 None.

    캐시는 data/raw/dart/{corp_code}_{op}_{year}_{reprt}.json 이다. "013"(자료 없음)을 캐시하면
    아직 제출 전인 최근 분기가 영원히 빈 칸으로 박제되므로 성공 응답만 남긴다.
    rebuild=True 면 캐시에 없는 칸을 호출하지 않고 없는 것으로 둔다(네트워크를 아예 쓰지 않는다).
    """
    path = RAW_DIR / f"{corp}_{op}_{year}_{reprt}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if rebuild:
        return None
    payload = _call(op, {"corp_code": corp, "bsns_year": str(year), "reprt_code": reprt})
    status = payload.get("status")
    if status == OK:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return payload
    if status == NODATA:
        return None
    if status in STOP_STATUS:
        raise _Stop(status, payload.get("message", ""))
    raise RuntimeError(f"DART {op} 비정상 status {status} ({corp} {year} {reprt}): "
                       f"{payload.get('message')}")


def fin_series(corp: str, rebuild: bool = False) -> tuple:
    """단일회사 주요계정(fnlttSinglAcnt) → (재무 행 목록, OFS 행이 없어 버린 응답 수).

    한 행 = 한 보고서. 자산·부채·자본은 재무상태표, revenue는 pick_revenue(손익계산서)에서 온다.
    basis 는 자산총계 행의 thstrm_dt(재무상태표 기준일)를 ISO 날짜로 정규화한 값이고, DART 의
    원문 표기는 basis_raw 에 그대로 남는다 — 결산월이 제각각인 리츠를 시간축에 올릴 때
    bsns_year 대신 이 값을 봐야 한다.
    """
    rows, skipped = [], 0
    for year in YEARS:
        for reprt in REPRTS:
            payload = _fetch(corp, "fnlttSinglAcnt", year, reprt, rebuild=rebuild)
            if payload is None:
                continue
            items = payload.get("list") or []
            row = {"year": year, "reprt": reprt, "assets": None, "liab": None,
                   "equity": None, "revenue": pick_revenue(items), "basis": "", "basis_raw": ""}
            for item in items:
                if item.get("fs_div") != "OFS":  # 개별(별도) 재무제표만
                    continue
                name = (item.get("account_nm") or "").strip()
                if name == "자산총계":
                    row["assets"] = _num(item.get("thstrm_amount"))
                    row["basis_raw"] = (item.get("thstrm_dt") or "").strip()
                    row["basis"] = _basis_date(row["basis_raw"])
                elif name == "부채총계":
                    row["liab"] = _num(item.get("thstrm_amount"))
                elif name == "자본총계":
                    row["equity"] = _num(item.get("thstrm_amount"))
            if row["equity"] is None and row["revenue"] is None:
                skipped += 1  # 응답은 왔지만 OFS 행이 없다(연결만 제출한 보고서)
                continue
            rows.append(row)
    return rows, skipped


def dividends(corp: str, rebuild: bool = False) -> list[dict]:
    """배당에 관한 사항(alotMatter) → 결산기(stlm_dt)별 보통주 현금배당.

    리츠는 반기·분기 결산이라 "연 1회 사업보고서" 가정이 깨진다. 그래서 bsns_year가 아니라
    결산기 블록 단위로 모으고, 여러 연도가 같은 결산기를 중복 보고하면 stlm_dt로 합친다.
    total_div 단위는 DART 표기대로 백만원, dps·yld 는 원·%다.
    """
    blocks: dict = {}
    for year in YEARS:
        payload = _fetch(corp, "alotMatter", year, "11011", rebuild=rebuild)
        if payload is None:
            continue
        for item in payload.get("list") or []:
            # **화이트리스트다.** "종류주"만 걸러내는 블랙리스트로 두면 우선주 배당이 그대로
            # 통과해 같은 결산기 블록의 보통주 dps를 소리 없이 덮어쓴다. 실제 캐시의 stock_knd
            # 분포가 {'-': 1233, '보통주': 320, '우선주': 116, '종류주': 56}이라 우선주를 배당하는
            # 리츠가 하나만 편입돼도 앵커가 오염된다. "-"는 종류 구분이 없는 표기다.
            if item.get("stock_knd") not in ("보통주", "-"):
                continue
            stlm = (item.get("stlm_dt") or "").strip()
            value = _num(item.get("thstrm"))
            if not stlm or value is None:
                continue
            kind = item.get("se", "")
            block = blocks.setdefault(stlm, {"stlm_dt": stlm})
            if "주당 현금배당금" in kind:
                block["dps"] = value
            elif "현금배당금총액" in kind:
                block["total_div"] = value
            elif "현금배당수익률" in kind:
                block["yld"] = value
    keep = [b for b in blocks.values() if "dps" in b or "total_div" in b]
    return sorted(keep, key=lambda b: b["stlm_dt"])


def _prior_fin_rows() -> int:
    """이미 저장돼 있는 산출이 담고 있는 재무 행 수. 파일이 없거나 못 읽으면 0."""
    try:
        return int(json.loads(OUT_PATH.read_text(encoding="utf-8"))["meta"]["fin_rows"])
    except Exception:
        return 0


def save_result(result: dict) -> Path:
    """산출을 쓴다. 이번 실행이 기존 산출보다 얇으면 덮어쓰지 않고 .partial 로 비켜 쓴다.

    쿼터 소진·인증키 거부로 중간에 멈춘 실행이 완성본을 얇은 결과로 덮어쓰면 커밋된 데이터가
    조용히 사라진다. raw 캐시가 이어받기의 근거이므로 비켜 써도 다음 실행은 중단 지점을 잇는다.
    """
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    prior, built = _prior_fin_rows(), result["meta"]["fin_rows"]
    if built < prior or (result["meta"]["stopped"] and built <= prior):
        result["meta"]["written_to"] = PARTIAL_PATH.name
        result["meta"]["partial_write_reason"] = (
            f"이번 실행은 재무 {built}행만 담았고 기존 산출은 {prior}행이라 덮어쓰지 않았다"
            f"{' (중단: ' + result['meta']['stopped'] + ')' if result['meta']['stopped'] else ''}. "
            f"다시 실행하면 raw 캐시를 이어받아 채운다.")
        PARTIAL_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        return PARTIAL_PATH
    result["meta"]["written_to"] = OUT_PATH.name
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return OUT_PATH


def _holding(ticker: str, meta: dict) -> str:
    """시드의 holding(direct|indirect|mixed)을 검증해 돌려준다.

    산출을 읽는 쪽이 재간접 여부를 알려면 note 산문에서 회사명을 파싱해야 했다. 별도 손익에
    임대료가 잡히는 리츠와 배당이 잡히는 리츠를 가르는 값이라 캘리브레이션 가중치가 여기서
    갈린다 — 기계가 읽을 수 있게 필드로 승격했다. 값이 없거나 낯설면 조용히 넘기지 않는다.
    """
    value = meta.get("holding")
    if value not in HOLDINGS:
        raise RuntimeError(f"시드 {ticker}({meta.get('name')})의 holding 이 {value!r}다. "
                           f"{sorted(HOLDINGS)} 중 하나여야 한다.")
    return value


def collect(rebuild: bool = False) -> dict:
    """리츠 10종의 재무·배당을 모아 산출을 쓰고 **결과를 돌려준다**.

    반환값이 필요한 이유: 중단(_Stop)으로 break 하고도 호출자가 그 사실을 알 방법이 없으면
    마지막 줄에 COMPLETE 를 찍게 된다. 쿼터 소진으로 절반만 받은 실행을 완주로 보고하는 것은
    데이터 계층에서 가장 비싼 거짓말이다 — meta.stopped 와 written_to 를 그대로 넘겨
    main() 이 COMPLETE/RESUME_NEEDED 를 가르게 한다(trades·buildings 와 같은 형태).
    """
    seed = json.load(open(SEED_PATH, encoding="utf-8"))
    tickers = list(seed["reits"])
    index = corp_index(tickers, rebuild=rebuild)
    print(f"  corp_code 매칭 {len(index)}/{len(tickers)}종"
          f"{' (--rebuild: 캐시만 읽는다)' if rebuild else ''}")

    out, stopped, skipped = {}, "", {}
    for ticker in tickers:
        meta = seed["reits"][ticker]
        corp = index[ticker]["corp_code"]
        try:
            fin, no_ofs = fin_series(corp, rebuild=rebuild)
            div = dividends(corp, rebuild=rebuild)
        except _Stop as e:
            stopped = str(e)
            print(f"  ⚠ {meta['name']}에서 중단: {stopped}")
            break
        skipped[ticker] = no_ofs
        out[ticker] = {"name": meta["name"], "corp_code": corp,
                       "holding": _holding(ticker, meta),
                       "office_assets": meta["office_assets"], "fin": fin, "div": div}
        linked = sum(1 for a in meta["office_assets"] if a["building_id"])
        span = f"{fin[0]['year']}~{fin[-1]['year']}" if fin else "없음"
        print(f"  {meta['name']:<12} fin {len(fin):>2}행({span})  배당 {len(div):>2}결산기  "
              f"오피스 {len(meta['office_assets'])}건(시드 연결 {linked})")

    fin_rows = sum(len(r["fin"]) for r in out.values())
    result = {
        "reits": out,
        "meta": {
            "collected_at": datetime.date.today().isoformat(),
            "source": "OpenDART",
            "note": ("자산·자본은 장부가 기준(감정 NAV 아님). revenue는 별도 손익계산서의 "
                     "최상단 수익이고 단위는 원이다 — 주요계정 API가 이 계정을 돌려주는 이름은 "
                     "실측 10종 모두 '매출액'이라 계정명으로 필터링하지 말고 이 필드를 써라. "
                     "재무는 별도(OFS) 기준이라 holding 이 indirect·mixed 인 리츠의 revenue 에는 "
                     "임대료가 아니라 자리츠·펀드 배당이 섞인다(holding 필드로 가중치를 정하라). "
                     "분기·반기 금액은 누적이 아니라 해당 기간분이고, 결산월이 리츠마다 달라 "
                     "시간축은 basis(재무상태표 기준일)로 잡아야 한다. revenue 가 null 인 행은 "
                     "주요계정 응답에 매출액 줄이 빠진 경우로, 손익 섹션과 영업이익은 와 있으니 "
                     "복원이 필요하면 fnlttSinglAcntAll(전체 재무제표)을 따로 받아야 한다. "
                     "basis 는 ISO 날짜(YYYY-MM-DD)로 정규화한 재무상태표 기준일이고, DART "
                     "원문 표기('2025.11.30 현재')는 basis_raw 에 그대로 남겼다. "
                     "배당의 total_div 단위는 백만원, dps는 원, yld는 %다."),
            "seed_as_of": seed["meta"]["as_of"],
            "seed_criteria": seed["meta"]["criteria"],
            "years": [YEARS.start, YEARS.stop - 1],
            "reprt_codes": list(REPRTS),
            "reits_count": len(out),
            "holdings": {h: sum(1 for r in out.values() if r["holding"] == h)
                         for h in sorted(HOLDINGS)},
            "holding_field": seed["meta"]["holding_field"],
            "fin_rows": fin_rows,
            # 주요계정(fnlttSinglAcnt)은 손익계산서를 보내면서도 최상단 매출액 한 줄을 빠뜨리는
            # 보고서가 있다 — 캐시 86건 전부 OFS 손익 섹션과 영업이익이 있는데 매출액은 68건뿐이다.
            # 그 행은 revenue=None 으로 남으므로 앵커로 쓸 수 있는 행수를 따로 적어 둔다.
            "fin_rows_with_revenue": sum(1 for r in out.values() for f in r["fin"]
                                         if f["revenue"] is not None),
            "div_rows": sum(len(r["div"]) for r in out.values()),
            "office_assets": sum(len(r["office_assets"]) for r in out.values()),
            "building_links": sum(1 for r in out.values()
                                  for a in r["office_assets"] if a["building_id"]),
            "skipped_no_ofs": skipped,  # 응답은 왔지만 별도(OFS) 행이 없어 버린 보고서 수
            "stopped": stopped,
        },
    }
    path = save_result(result)
    print(f"  저장: {path} (리츠 {len(out)}종 · 재무 {fin_rows}행 · "
          f"배당 {result['meta']['div_rows']}행)")
    if stopped:
        print(f"  중단 사유가 기록됐다: {stopped} — 다음 실행이 raw 캐시를 이어받는다.")
    if result["meta"].get("partial_write_reason"):
        print(f"  ⚠ 기존 산출을 지키려고 비켜 썼다: {result['meta']['partial_write_reason']}")
    return result


def main() -> None:
    # --rebuild: 네트워크를 아예 쓰지 않고 raw 캐시만으로 산출을 다시 만든다(스키마 변경 반영용).
    rebuild = "--rebuild" in sys.argv[1:]
    print("DART 리츠 앵커 수집:" if not rebuild else "DART 리츠 앵커 재생성(캐시만):")
    meta = collect(rebuild=rebuild)["meta"]
    # 완주는 두 조건을 모두 만족할 때뿐이다. 중단 사유가 없어야 하고, 산출이 제자리(reits.json)에
    # 앉아야 한다. 기존 산출보다 얇아 .partial 로 비켜 쓴 실행도 이어받을 일이 남은 것이다.
    print("COMPLETE" if not meta["stopped"] and meta["written_to"] == OUT_PATH.name
          else "RESUME_NEEDED")


if __name__ == "__main__":
    main()
