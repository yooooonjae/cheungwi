"""수집 공통: 설정 로드, HTTP 호출(오류 삼킴 금지), 시도 코드표."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
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
    return json.load(open(ROOT / "config.json"))


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
