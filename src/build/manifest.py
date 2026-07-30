"""DATA_MANIFEST.json 생성 — 여섯 원천의 공통 데이터 원장.

원장은 원천마다 다음을 나눠 적는다.
  - dataset·institution·source : 무엇을, 어느 기관의 어느 데이터셋에서 받았는가
  - observed_through : 데이터가 실제 **관측**하는 마지막 시점(관측월)
  - collected_at     : API 를 불러 **수집**한 날짜(수집일)
  - rows             : 데이터 규모 — 원천마다 세는 단위가 다르다.
                       건물은 동 수, 실거래는 거래 건수, 지수·금리·리츠 재무는 관측치 수다.
  - coverage         : 지역·주기·기간과 **빠진 부분**까지 한 줄로 적은 커버리지
  - cache            : 재실행이 어디까지 캐시를 믿는가 — 수집기마다 정책이 다르다
  - units            : 그 산출의 수치가 어느 단위로 적혀 있는가. 원·㎡·지수·%·연%가 한 원장에
                       섞이는데 단위를 적어 두지 않으면 소비자가 값의 자릿수를 보고 되짚어야
                       한다(리츠 total_div 만 백만원인 것이 대표적인 함정이다).

관측월과 수집일의 간격이 곧 데이터 지연이다. 두 값을 뭉뚱그리지 않는 것이 이 파일의 목적이다.
같은 날 수집해도 R-ONE 은 2026Q1(분기 지표), 금리는 2026-06, 실거래는 당일까지 관측한다.

data_cutoff = **자기 시점축을 가진** 원천(trades·rone_office·reits·rates)의 관측월 중 완결된
              달의 최신 월. 완결 판정선은 오늘과 수집일 중 이른 달이다 — 재수집 없이 달만
              넘어가도 기준월이 저 혼자 전진하지 않게 하려는 것이다. 시드·건물 마스터는
              관측월이 수집일에서 나오는 스냅샷이라 후보에서 뺀다(time_axis=False).
              사이트가 "언제까지의 데이터인가"로 내거는 값이다.

실행:  python3 src/build/manifest.py      →  data/DATA_MANIFEST.json 기록·요약 출력
사용:  from src.build.manifest import build_manifest
"""

import datetime
import json
import re
from collections import namedtuple
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
MANIFEST_PATH = DATA / "DATA_MANIFEST.json"

_YM = re.compile(r"^(19|20)\d{2}(0[1-9]|1[0-2])$")
_YQ = re.compile(r"^(19|20)\d{2}Q[1-4]$")


# ------------------------------------------------------------------ #
# 시점 파싱·재귀 스캐너 — 중첩 구조(권역→계열→분기)에 무관하게 관측 시점을 모은다
# ------------------------------------------------------------------ #
def _to_ym(v):
    """'2026-07-23'·'202607'·'2026.05.31 현재'·'2026-07' → '202607'. 아니면 None."""
    if not isinstance(v, (str, int)):
        return None
    s = re.sub(r"\D", "", str(v))[:6]
    return s if _YM.match(s) else None


def _scan_months(obj, keys, out):
    """지정한 키의 값에서만 YYYYMM 을 모은다.

    키를 한정하는 이유: meta.collected_at 까지 긁으면 관측월이 수집월로 밀린다.
    리츠 basis 최신월 2026-05 가 수집일 2026-07 로 둔갑하는 식이다.
    """
    if isinstance(obj, dict):
        for k in keys:
            ym = _to_ym(obj.get(k))
            if ym:
                out.append(ym)
        for v in obj.values():
            _scan_months(v, keys, out)
    elif isinstance(obj, list):
        for v in obj:
            _scan_months(v, keys, out)


def _scan_quarters(obj, out):
    if isinstance(obj, dict):
        v = obj.get("yq")
        if isinstance(v, str) and _YQ.match(v):
            out.append(v)
        for v in obj.values():
            _scan_quarters(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _scan_quarters(v, out)


def _span_months(obj, keys):
    ms = []
    _scan_months(obj, keys, ms)
    return (min(ms), max(ms)) if ms else (None, None)


def _fmt_month(yyyymm):
    return f"{yyyymm[:4]}-{yyyymm[4:6]}" if yyyymm else None


def _quarter_end_month(yq):
    """'2026Q1' → '2026-03'. 분기 지표의 관측월은 그 분기의 마지막 달이다."""
    if not yq:
        return None
    return f"{yq[:4]}-{int(yq[5]) * 3:02d}"


# ------------------------------------------------------------------ #
# 원천별 핸들러 — 각 값이 실데이터에서 어떻게 나오는지 명시적으로 계산한다
# ------------------------------------------------------------------ #
def _h_seed(d):
    rows = d["buildings"]
    meta = d["meta"]
    as_of = str(meta.get("as_of", ""))[:10]
    by_region = {}
    for b in rows:
        by_region[b["region"]] = by_region.get(b["region"], 0) + 1
    gu = {b["sgg_cd"] for b in rows}
    order = " · ".join(f"{r} {by_region.get(r, 0)}" for r in ("CBD", "GBD", "YBD"))
    return dict(
        observed_through=_fmt_month(_to_ym(as_of)),
        collected_at=as_of,
        rows=len(rows),
        coverage=f"{len(rows)}동({order}) · 서울 {len(gu)}개 구 · "
                 f"손으로 고른 표본이라 관측월은 시드 확정일이다",
    )


def _h_buildings(d):
    rows = d["buildings"]
    meta = d["meta"]
    collected = str(meta.get("collected_at", ""))[:10]
    ledger = sum(1 for b in rows if b.get("ledger"))
    vworld = sum(1 for b in rows if b.get("vworld"))
    tail = "" if meta.get("complete") else " · 대장은 활용신청 승인 대기라 연면적·층수·준공년도가 비어 있다"
    return dict(
        observed_through=_fmt_month(_to_ym(collected)),
        collected_at=collected,
        rows=len(rows),
        coverage=f"{len(rows)}동 · 대장 {ledger}/{len(rows)}, VWorld {vworld}/{len(rows)} · "
                 f"좌표·용도지역·공시지가 병합{tail}",
    )


def _h_trades(d):
    rows = d["trades"]
    meta = d["meta"]
    lo, hi = _span_months(rows, ("deal_ymd",))
    # 매칭은 세 단계다. match 가 붙은 행 중 building_id 가 채워진 것만 동이 확정된 것이고,
    # 나머지는 마스킹 지번이 여러 시드에 걸려 후보만 달아 둔 행이다 — 뭉뚱그리면 과장이 된다.
    attached = sum(1 for r in rows if r.get("match"))
    resolved = sum(1 for r in rows if (r.get("match") or {}).get("building_id"))
    done, total = meta.get("cells_done", 0), meta.get("cells_total", 0)
    cells = f"셀 {done:,}/{total:,}" + ("" if meta.get("complete") else " (수집 진행 중)")
    basis = "지번만으로 붙였다(대장 미개통)" if not meta.get("ledger_ready") else "대장 연면적 대조"
    return dict(
        observed_through=_fmt_month(hi),
        collected_at=str(meta.get("collected_at", ""))[:10],
        rows=len(rows),
        coverage=f"서울 {len(meta.get('sgg_list', []))}개 구 · 업무용 매매 {len(rows):,}건 · "
                 f"{_fmt_month(lo)}~{_fmt_month(hi)} · {cells} · "
                 f"시드 매칭 {attached:,}건(동 확정 {resolved:,}·후보 다수 {attached - resolved:,}) · {basis}",
    )


def _h_rone(d):
    qs = []
    _scan_quarters(d, qs)
    lo, hi = (min(qs), max(qs)) if qs else (None, None)
    regions = d.get("regions", {})
    subs = d.get("sub_regions", {})
    series = sorted({s for v in regions.values() for s in v})
    short = {"rent_index": "임대지수", "vacancy": "공실률", "rent_level": "임대료", "yield": "수익률"}
    label = "·".join(short.get(s, s) for s in series)  # 계열이 늘면 이름도 같이 는다
    reg_pts = sum(len(x) for v in regions.values() for x in v.values())
    sub_pts = sum(len(x) for v in subs.values() for x in v.values())
    nq = len(set(qs))
    # 하위 상권은 키 수가 곧 상권 수가 아니다. R-ONE 이 기간표마다 명칭을 바꿔(신사→신사역)
    # 옛 이름 키가 중간 분기에서 끊긴다. 최신 분기까지 살아 있는 키만 따로 세어 결손을 드러낸다.
    alive = sum(1 for v in subs.values()
                if any(p.get("yq") == hi for x in v.values() for p in x))
    full = sum(len(v) for v in subs.values()) * nq  # 끊김이 없을 때의 사각형 점수
    return dict(
        observed_through=_quarter_end_month(hi),
        collected_at=str(d["meta"].get("collected_at", ""))[:10],
        rows=reg_pts + sub_pts,
        coverage=f"{len(regions)}개 권역(3대 권역+서울) × {len(series)}계열({label}) "
                 f"{nq}분기 {reg_pts:,}점 + 하위 상권 {hi} 기준 {alive}곳"
                 f"(명칭 분기로 끊긴 키 포함 {len(subs)}키) {sub_pts:,}/{full:,}점 · "
                 f"{lo}~{hi} 분기",
    )


def _h_reits(d):
    reits = d["reits"]
    meta = d["meta"]
    _, hi = _span_months(reits, ("basis",))
    fin = sum(len(v.get("fin", [])) for v in reits.values())
    div = sum(len(v.get("div", [])) for v in reits.values())
    rev = sum(1 for v in reits.values() for f in v.get("fin", []) if f.get("revenue") is not None)
    hold = {}
    for v in reits.values():
        hold[v.get("holding")] = hold.get(v.get("holding"), 0) + 1
    label = {"direct": "직접", "indirect": "간접", "mixed": "혼합"}
    mix = "·".join(f"{label.get(k, k)} {n}" for k, n in sorted(hold.items()) if k)
    years = meta.get("years", [])
    span = f"{years[0]}~{years[-1]}" if years else ""
    return dict(
        observed_through=_fmt_month(hi),
        collected_at=str(meta.get("collected_at", ""))[:10],
        rows=fin + div,
        coverage=f"오피스 보유 상장리츠 {len(reits)}종(보유형태 {mix}) · "
                 f"재무 {fin}행(매출액 {rev}행)·배당 {div}행 · {span} 정기보고서 · "
                 f"시간축은 결산월이 갈려 재무상태표 기준일(basis)이다",
    )


def _h_rates(d):
    meta = d["meta"]
    # 계열은 meta.stat_codes 가 단일 출처다. "meta 만 빼기" 식으로 고르면 상위 키가 하나 늘 때
    # 그것까지 계열로 세어 rows 가 조용히 오염된다.
    keys = meta.get("stat_codes") or d
    series = [k for k in keys if isinstance(d.get(k), list)]
    lo, hi = _span_months({k: d[k] for k in series}, ("ym",))
    pts = sum(len(d[k]) for k in series)
    names = meta.get("series_names", {})
    short = {"treasury10y": "국고채10년", "cd91": "CD91일", "loan_corp_new": "기업대출(신규)"}
    label = "·".join(short.get(k, names.get(k, k)) for k in series)
    counts = [len(d[k]) for k in series]
    per = f"{min(counts)}" if min(counts) == max(counts) else f"{min(counts)}~{max(counts)}"
    # 관측월은 계열 최댓값이지만, 계열마다 최신월이 갈리면 그 사실을 커버리지에 드러낸다.
    # 한 계열만 먼저 갱신돼도 원장은 전 계열이 그 달까지 온 것처럼 보이기 때문이다.
    last = {k: _span_months(d[k], ("ym",))[1] for k in series}
    lag = [k for k in series if last[k] != hi]
    gap = ""
    if lag:
        gap = " · 계열별 최신월 상이: " + "·".join(
            f"{short.get(k, k)} {_fmt_month(last[k])}" for k in lag
        ) + f" (그 외 {_fmt_month(hi)})"
    return dict(
        observed_through=_fmt_month(hi),
        collected_at=str(meta.get("collected_at", ""))[:10],
        rows=pts,
        coverage=f"{label} {len(series)}계열 · 계열당 {per}개월 · "
                 f"{_fmt_month(lo)}~{_fmt_month(hi)} 월별{gap}",
    )


# time_axis: 데이터 자체에 시점 축이 있는가. 시드와 건물 마스터는 스냅샷이라 관측월이
# 수집일에서 나온다 — 그런 원천을 data_cutoff 후보에 넣으면, 재수집 없이 달만 넘겨도
# 기준월이 저 혼자 앞으로 간다. 그래서 후보 자격을 이 플래그로 가른다.
Source = namedtuple("Source", "key dataset institution handler time_axis cache units")

# 표시 순서 = 사이트 방법론 표 순서
SOURCES = [
    Source("seed_buildings", "3대 권역 프라임 오피스 시드", "직접 작성(공개 자료 대조)", _h_seed, False,
           "API 를 부르지 않는다. 사람이 고쳐 쓰는 단일 출처이고 다른 수집기가 이 지번을 기준으로 조회한다.",
           "-"),
    Source("buildings", "건축물대장 표제부 + 좌표·용도지역·공시지가", "국토교통부 건축HUB · VWorld",
           _h_buildings, False,
           "VWorld 는 입력 지문·완전성 검사를 거쳐 캐시한다(조회 입력이 바뀌거나 반쪽 결과면 캐시를 "
           "쓰지 않는다). 대장 표제부 XML 은 캐시 우선이고 무효화가 없다 — 활용신청이 승인된 뒤 "
           "받은 첫 응답이 그대로 스냅샷으로 얼어붙으므로, 대장이 갱신됐는지 보려면 "
           "data/raw/bldrgst/ 를 지우고 다시 돌려야 한다.",
           "㎡·원/㎡(공시지가)"),
    Source("trades", "서울 5개 구 상업업무용 실거래", "국토교통부 RTMS", _h_trades, True,
           "캐시 우선 + 진행 파일(trades_progress.json)로 중단 지점 재개. raw 캐시가 단일 진실이라 "
           "매 실행이 캐시 전체를 다시 읽어 산출을 새로 만든다.",
           "원·㎡"),
    Source("rone_office", "상업용부동산 임대동향(오피스)", "한국부동산원 R-ONE", _h_rone, True,
           "표(STATBL_ID) 단위 캐시 우선이고 무효화가 없다 — 새 분기를 받으려면 "
           "data/raw/rone_office/ 를 지우고 다시 돌려야 한다.",
           "지수·%·천원/㎡"),
    Source("reits", "오피스 보유 상장리츠 재무·배당", "금융감독원 OpenDART", _h_reits, True,
           "성공 응답(status 000)만 캐시한다. '자료 없음'은 아직 제출 전일 수 있어 캐시하지 않고 "
           "다음 실행이 다시 부른다.",
           "원(total_div만 백만원)"),
    Source("rates", "국고채 10년·CD 91일·기업대출 금리", "한국은행 ECOS", _h_rates, True,
           "캐시가 있어도 매 실행 API 를 다시 부른다 — 월 시계열이라 최신 월이 계속 늘기 때문이다.",
           "연%"),
]


def build_manifest(write: bool = True, today=None, data_dir=None) -> dict:
    """data/*.json 을 읽어 원장을 만든다. write=True 면 DATA_MANIFEST.json 을 기록한다.

    today·data_dir 는 주입구다. 달 롤오버와 결손 입력은 실데이터로는 재현할 수 없어
    테스트가 날짜와 입력 디렉터리를 갈아 끼우고 규칙을 확인한다.
    """
    today = today or datetime.date.today()
    cur_ym = today.strftime("%Y%m")
    data_dir = Path(data_dir) if data_dir else DATA
    sources = []
    complete_months = []  # data_cutoff 후보 — 시점축이 있고 완결된 달만 들어온다

    for src in SOURCES:
        path = data_dir / f"{src.key}.json"
        if not path.exists():
            raise FileNotFoundError(f"manifest: {path} 없음 — 해당 수집기를 먼저 돌려야 한다")
        d = json.loads(path.read_text(encoding="utf-8"))
        info = src.handler(d)
        ot = info["observed_through"]
        # 빈 산출을 원장에 조용히 싣지 않는다. 관측월이나 행이 없으면 그 자리에서 실패시킨다.
        if not ot or info["rows"] < 1:
            raise RuntimeError(f"manifest: {src.key} 관측월={ot} 행수={info['rows']} — 산출이 비었다")
        sources.append({
            "key": src.key,
            "dataset": src.dataset,
            "institution": src.institution,
            "source": d.get("meta", {}).get("source", src.institution),
            "observed_through": ot,
            "collected_at": info["collected_at"],
            "time_axis": src.time_axis,
            "rows": info["rows"],
            "coverage": info["coverage"],
            "cache": src.cache,
            "units": src.units,
        })
        if not src.time_axis:
            continue
        # 완결 판정선은 오늘과 수집일 중 이른 달이다. 수집일 달까지만 데이터가 있는데
        # 달이 넘어갔다고 그 달을 완결로 치면, 재수집 없이 기준월만 앞으로 간다.
        collected_ym = re.sub(r"\D", "", info["collected_at"])[:6]
        limit = min(cur_ym, collected_ym) if _YM.match(collected_ym or "") else cur_ym
        if ot.replace("-", "") < limit:
            complete_months.append(ot.replace("-", ""))

    if not complete_months:
        raise RuntimeError("manifest: 완결된 관측월이 하나도 없다 — data_cutoff 를 정할 수 없다")

    manifest = {
        "generated_at": today.isoformat(),
        "data_cutoff": _fmt_month(max(complete_months)),
        "source_count": len(sources),
        "sources": sources,
    }
    if write:
        (data_dir / "DATA_MANIFEST.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    m = build_manifest(write=True)
    print(f"DATA_MANIFEST.json — {m['source_count']}개 원천 · 데이터 기준월 {m['data_cutoff']}")
    print(f"{'원천':<14}{'관측월':<9}{'수집일':<11}{'규모':>8}")
    print("-" * 54)
    for s in m["sources"]:
        print(f"{s['key']:<16}{s['observed_through']:<11}{s['collected_at']:<13}{s['rows']:>10,}")
    print(f"\n→ {MANIFEST_PATH}")
