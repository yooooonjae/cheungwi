"""수집 공통: 설정 로드, HTTP 호출(오류 삼킴 금지), 시도 코드표, data.go.kr 오류 봉투 해석."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# 행정표준코드(법정동 시도 2자리) — 전국 17개 시도 단일 출처
SIDO = {
    "11": "서울", "26": "부산", "27": "대구", "28": "인천", "29": "광주",
    "30": "대전", "31": "울산", "36": "세종", "41": "경기", "43": "충북",
    "44": "충남", "45": "전북", "46": "전남", "47": "경북", "48": "경남",
    "50": "제주", "42": "강원",
}

# 서울 25개 자치구 법정동 시군구 5자리. 층위 표본은 이 중 5개 구만 쓰지만 전체를 상수로 둔다.
SEOUL_GU = {
    "11110": "종로구", "11140": "중구", "11170": "용산구", "11200": "성동구",
    "11215": "광진구", "11230": "동대문구", "11260": "중랑구", "11290": "성북구",
    "11305": "강북구", "11320": "도봉구", "11350": "노원구", "11380": "은평구",
    "11410": "서대문구", "11440": "마포구", "11470": "양천구", "11500": "강서구",
    "11530": "구로구", "11545": "금천구", "11560": "영등포구", "11590": "동작구",
    "11620": "관악구", "11650": "서초구", "11680": "강남구", "11710": "송파구",
    "11740": "강동구",
}


def load_config() -> dict:
    return json.load(open(ROOT / "config.json", encoding="utf-8"))


def api_get(url: str, params: dict, timeout: int = 15, retries: int = 1, headers: dict = None):
    """GET 호출. (status_code, text) 반환 — 예외도 상태로 환원해 호출자가 반드시 보게 한다.

    headers: 기본 User-Agent에 병합할 추가 헤더. 건축HUB(ArchPmsHubService)는 Accept 헤더가
    없으면 HTTP 200 + 빈 바디를 돌려주므로 {"Accept": "*/*"} 를 반드시 넘겨야 한다(2026-07-21 실측).
    """
    qs = urllib.parse.urlencode(params, safe="%")
    # 빈 쿼리에 '?'를 붙이면 일부 게이트웨이(ECOS 등)가 경로 파싱에 실패한다
    full = f"{url}?{qs}" if qs else url
    hdrs = {"User-Agent": "cheungwi/0.1"}
    if headers:
        hdrs.update(headers)
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(full, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", errors="replace")
        except Exception as e:  # URLError, timeout 등
            last_err = e
            if attempt < retries:
                time.sleep(1.5)
    return -1, f"NETWORK_ERROR: {last_err}"


def call_with_backoff(fn, tries=5, base_sleep=2.0):
    """fn() -> (status, text) 를 최대 tries회 시도. 5xx·-1(네트워크)만 백오프 재시도.

    기존 시리즈에서 rone/rtms/archub가 각자 구현하던 루프의 공통화.
    4xx는 즉시 반환한다(키·파라미터 문제는 재시도해도 소용없다).
    """
    status, text = -1, ""
    for attempt in range(tries):
        status, text = fn()
        if status == 200:
            return status, text
        if 400 <= status < 500:
            return status, text
        time.sleep(base_sleep * (attempt + 1))
    return status, text


# ── data.go.kr 게이트웨이 오류 봉투 ───────────────────────────────────────────
# 대장(BldRgstHubService)·실거래(RTMSDataSvc*)가 같은 게이트웨이를 쓴다. 쿼터 소진·권한 거부를
# 한쪽에서만 알아보면 다른 쪽은 '빈 응답'으로 오인해 재시도만 하다 하루 쿼터를 태운다.
# 그래서 봉투 해석은 여기 한 곳에만 둔다 — 성격→행동 매핑(예외로 올릴지, 저장하고 끝낼지)만
# 각 수집기가 정한다.

ENVELOPE_DENIED = {"20", "30", "31", "32", "33"}  # 권한 없음·미등록 키·기한 만료·미등록 IP
ENVELOPE_QUOTA = {"22"}                           # 일일 트래픽 초과
ENVELOPE_NODATA = {"03"}                          # 데이터 없음
ENVELOPE_TRANSIENT = {"01", "02", "04", "05", "21"}  # 앱·DB 오류·HTTP 오류·타임아웃·일시중지

# 메시지 → 성격. **코드보다 이쪽을 먼저 본다**(아래 classify_envelope 참조).
ENVELOPE_MSG_RULES = (
    ("nodata", ("NODATA",)),
    ("quota", ("LIMITED_NUMBER_OF_SERVICE_REQUESTS",)),
    ("denied", ("SERVICE_ACCESS_DENIED", "SERVICE_KEY_IS_NOT_REGISTERED",
                "DEADLINE_HAS_EXPIRED", "UNREGISTERED_IP", "UNSIGNED_CALL")),
    ("transient", ("HTTP_ERROR", "SERVICETIMEOUT", "TEMPORARILY_DISABLE",
                   "DB_ERROR", "APPLICATION_ERROR")),
)


def _norm_reason_code(code: str):
    """사유코드의 자릿수 변형을 2자리 정규형으로. 읽기가 갈리면 None(모름).

    이 게이트웨이는 같은 뜻을 2자리로도 3자리로도 보낸다("00"과 "000"이 함께 쓰인다).
    그런데 3자리 "030"은 앞 0을 떼면 "30"(권한 없음), 뒤 0을 떼면 "03"(데이터 없음)이라
    **뜻이 정반대로 갈린다.** 한쪽으로 단정하면 건별로 끝났어야 할 '데이터 없음'이 전역
    차단으로 승격돼 남은 전 건을 생략해 버린다. 그래서 갈리면 모른다고 답한다.
    """
    c = (code or "").strip()
    if not c.isdigit():
        return None
    if len(c) <= 2:
        return c.zfill(2)
    readings = {c.lstrip("0").zfill(2)}
    if c.endswith("0"):
        readings.add(c[:-1].lstrip("0").zfill(2))
    return readings.pop() if len(readings) == 1 else None


def classify_envelope(code: str, msg: str) -> str:
    """(사유코드, 메시지) → "nodata"|"quota"|"denied"|"transient"|"unknown".

    **메시지를 코드보다 먼저 본다.** 게이트웨이는 returnAuthMsg를 늘 정형 문자열로
    보내지만(NODATA_ERROR 등) 사유코드는 자릿수가 흔들려 "030"처럼 뜻이 갈리는 값이 온다.
    """
    upper = (msg or "").upper()
    for kind, needles in ENVELOPE_MSG_RULES:
        if any(n in upper for n in needles):
            return kind
    norm = _norm_reason_code(code)
    if norm in ENVELOPE_NODATA:
        return "nodata"
    if norm in ENVELOPE_QUOTA:
        return "quota"
    if norm in ENVELOPE_DENIED:
        return "denied"
    if norm in ENVELOPE_TRANSIENT:
        return "transient"
    return "unknown"


def envelope_error(xml_text: str):
    """data.go.kr 게이트웨이 오류 봉투 → (사유코드, 메시지). 봉투가 아니면 None.

    이 게이트웨이는 오류를 **HTTP 200 + 다른 루트 엘리먼트**로 돌려준다. 정상 응답의
    `<response><header><resultCode>` 대신 `<OpenAPI_ServiceResponse><cmmMsgHeader>`가 오므로
    resultCode만 보고 판정하면 쿼터 소진·권한 거부가 '빈 응답'으로 오인돼 재시도만 하다 죽는다.
    """
    if "cmmMsgHeader" not in (xml_text or ""):
        return None
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    hdr = root.find(".//cmmMsgHeader")
    if hdr is None:
        return None
    code = (hdr.findtext("returnReasonCode") or "").strip()
    msg = (hdr.findtext("returnAuthMsg") or hdr.findtext("errMsg") or "").strip()
    return code, msg
