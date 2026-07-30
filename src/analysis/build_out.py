"""적용기 — 엔진을 실데이터에 붙여 `out/*.json` 네 종을 만든다.

`src/analysis/` 의 다른 일곱 모듈은 순수 함수다(I/O 도 전역 상태도 없다).
파일을 읽고 쓰는 자리는 여기 하나뿐이고, 이 모듈이 하는 일은 계산이 아니라
**연결**이다 — 데이터층이 준 값의 단위를 엔진의 규약으로 옮기고, 엔진이 던지는
게이트와 신호를 산출물에 그대로 실어 보낸다.

    market.json           권역 3종의 유효임대료·공실·cap 벤치마크·금리·스프레드
    underwriting.json     시드 55동의 언더라이팅(대장이 없으면 pending_ledger)
    trades_analysis.json  해제 제외 실거래의 권역별·연도별 중위 평당가와 매칭 사다리
    pf_case.json          대표 가상 사업지의 월별 스케줄과 스트레스 15행

## 데이터 소비 계약(`docs/plan2-3-handoff.md` + 선행 태스크 리뷰)

1. **`rone_office.rent_level` 은 천원/㎡·월이다.** ×1000 해서 원으로 옮긴 뒤에
   엔진에 넘긴다. 그대로 넘기면 유효임대료가 1000분의 1 이 되어 물리 게이트에
   걸린다(걸리는 것이 다행이다 — 게이트가 없는 축이면 조용히 틀린다).
2. **임대료 수치에는 `region_params()["_meta"]` 를 동봉한다.** 렌트프리 개월 수는
   관측치가 아니라 조정 가능한 가정이고, 그 라벨 없이 나간 임대료는 하류에서
   실측처럼 인용된다.
3. **`ledger` 가 null 인 건물은 `building_adjust`·`noi` 에 도달시키지 않는다.**
   그 함수들은 연면적·연식을 수치로 받으므로 `None` 이 들어가면 도메인 검사가
   아니라 맨 `TypeError` 로 죽는다. 지금 55동 **전부** null 이라 이 분기가 곧
   실데이터의 전부다 — 대장 부재를 0 이나 평균으로 메우지 않고 `pending_ledger`
   로 그대로 싣는다.
4. **`caprate.benchmark` 는 4분기 미만 계열에 `ValueError` 다.** 하위 상권에는
   2분기짜리 계열(서울>강남>신사)이 있어 호출 **전에** 길이로 거른다. 권역
   3종은 39분기라 안전하다. 거른 계열은 사유와 함께 산출물에 남긴다.
5. **`canceled=true` 404행은 가격 집계 전에 거른다.** 해제된 계약도 그 시점의
   호가 정보라 데이터층이 보존해 두었고, 거르는 판단은 이쪽 몫이다.
6. **필지까지 확정된 것은 `match_exact` 57행뿐이다.** `building_id` 가 채워진
   734행(`match_resolved`)은 "시드 55동 목록 안에서 후보가 유일"이라는 뜻이지
   같은 법정동의 비-시드 건물과 구분된 것이 아니다. 라벨을 갈라 싣는다.
   **두 수는 배타적이 아니다** — exact ⊆ resolved 라 그대로 더하면 exact 를 두 번
   센다(57 + 734 + 3,789 = 4,580 ≠ 4,523). 배타적 사다리는 exact 57 +
   resolved_only 677 + ambiguous 3,789 = 4,523 이고, 그 세 칸을
   `matching.ladder_exclusive` 로 따로 낸다.
7. **리츠 `revenue` 는 `holding` 으로 가른다.** indirect·mixed 의 별도 영업수익은
   임대료가 아니라 배당·이자다. 앵커 후보는 direct 뿐이다.

## 예외를 잡는 순서

`NotImplementedError` 는 `RuntimeError` 의 **하위형**이다(MRO: NotImplementedError
→ RuntimeError). 이 저장소의 분석 계층에서 `RuntimeError` 는 "단위·자릿수를
의심하라"는 뜻으로만 쓰이는데, 순서를 뒤집으면 "계산할 수 없다"는 신호가 단위
오류로 오분류된다. 그래서 건물 단위 언더라이팅은 늘

    except NotImplementedError:   # 계산 불가 — 입력을 고쳐도 안 된다
    except RuntimeError:          # 물리 게이트 위반 — 단위를 의심하라
    except ValueError:            # 입력이 물리적으로 말이 안 된다

순서로 잡는다.

## 게이트를 만나면 시끄럽게 군다

물리 게이트(cap 0.02~0.12 · 유효임대료 10,000~60,000원/㎡·월 · DSCR 0~5 ·
LTC 0~1)를 만났을 때 이 모듈이 하는 일은 둘 중 하나다.

- **권역 3종의 최신 유효임대료·cap** 과 **PF 대표 사업지**는 예외를 그대로 올린다.
  그 값이 없으면 산출물이 성립하지 않고, 조용한 `null` 은 대시보드에서
  "자료 없음"으로 읽혀 사고가 묻힌다.
- **하위 상권·서울 참고 계열·건물 단위·권역 추이**의 개별 지점은 그 지점만
  `null` 로 두고 `gate_violations`(market)·`errors`(underwriting)에 사유 문구를
  싣고 stderr 로 경고를 찍는다. 한 지점 때문에 나머지 스물두 상권을 잃지
  않으면서도, 빠진 자리가 산출물 안에서 이름과 사유를 갖게 하려는 것이다.

  하위 상권 cap 이 특히 그렇다 — GBD 상권 여럿(도산대로 2.3992% · 교대역
  2.3638% · 신사역 2.4851%)이 게이트 하한 2% 에서 0.5%p 안쪽이고, 도산대로는
  직전 창(2024Q2~2025Q1)에서 1.4756% 로 실제로 하한을 밑돌았다. 여기서 예외를
  올리면 R-ONE 한 분기 갱신에 `make analyze` 전체가 죽는다.

`refi_test` 의 `implausible` 은 게이트가 아니라 **신호**다(예외를 던지지도
판정을 바꾸지도 않는다). 켜진 건은 산출물 최상위 `implausible_refi` 에 사유
문구까지 모아 둔다 — 부르는 쪽이 읽지 않으면 아무 일도 일어나지 않는 값이라
파이프라인이 대신 드러낸다.

## 멱등

같은 입력이면 같은 바이트가 나온다. 벽시계 시각을 싣지 않고 시간 도장은 전부
데이터에서 뽑는다(`meta.collected_at`, 최신 분기·최신 월). 쓰기는 조립을 모두
끝낸 뒤에 하고(`tmp` → `os.replace`), 조립 도중 예외가 나면 기존 `out/` 은
한 글자도 바뀌지 않는다.
"""

import json
import os
import statistics
import sys
from datetime import date
from pathlib import Path

from src.analysis import caprate, effective_rent, noi as noi_mod, pf, refi, value
from src.analysis.acquisition import hold_model, max_loan

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = ROOT / "data"
DEFAULT_OUT_DIR = ROOT / "out"

OUT_FILES = ("market.json", "underwriting.json", "trades_analysis.json", "pf_case.json")
DATA_FILES = ("rone_office", "rates", "trades", "buildings", "seed_buildings", "reits")

# 1평 = 400/121 ㎡ (정확값). 3.3 으로 반올림하면 평당가가 0.17% 어긋난다.
PYEONG_M2 = 400 / 121
# rent_level 은 천원/㎡·월이다(계약 1). 이 상수를 거치지 않는 환산을 두지 않는다.
THOUSAND_WON = 1000.0
PERCENT = 100.0
BP_PER_UNIT = 10_000.0

# 권역 3종. `REGIONS` 순서가 산출물의 키 순서다(멱등).
REGIONS = ("도심", "강남", "여의도마포")
# R-ONE 은 '서울' 계열도 준다 — 렌트프리 가정이 권역 3종에만 있어 유효임대료를
# 만들지 않고 명목·공실·cap 만 참고로 싣는다.
SEOUL_KEY = "서울"

# 추이에 싣는 길이. 분기 계열은 3년, 월 계열은 1년이다.
TREND_QUARTERS = 12
TREND_MONTHS = 12

# 언더라이팅 가정(조정 가능한 값이며 대주 심사 결과가 아니다).
EFFICIENCY = noi_mod.DEFAULT_EFFICIENCY      # 0.5 — GFA 대비 임대면적
OPEX_RATIO = noi_mod.DEFAULT_OPEX_RATIO      # 0.15 — 관리비 상계 후 미회수분
LTV_MAX = 0.55
DSCR_MIN = 1.3
DEBT_YIELD_MIN = 0.08
REFI_LTV_MAX = 0.60
NOI_GROWTH_Y = 0.02
HOLD_YEARS = 5
ACQ_COST_RATE = 0.05
# 역까지 거리를 담은 데이터층이 없다. 0 이나 임의값을 넣지 않고 판단을 보류한다
# (`building_adjust` 가 1.0 을 주고 caveat 에 '유보'로 남긴다).
DIST_SUBWAY_M = None

# PF 대표 사업지 — 강남권 중형 오피스(가상). 실측 앵커와 가정을 갈라 둔다.
PF_PLOT_M2 = 3_000.0             # 대지면적(가정)
PF_FAR = 8.0                     # 용적률 800%(일반상업지역 상한 수준, 가정)
PF_BASEMENT_RATIO = 0.375        # 지하 연면적 / 지상 연면적(가정)
PF_HARD_COST_WON_M2 = 1_800_000  # 공사비 단가(가정) ≈ 595만원/평
PF_LAND_PRICE_WON_M2 = 12_000_000   # 토지 단가(가정) ≈ 3,967만원/평
PF_MONTHS_BUILD = 30
PF_LEASE_UP_MONTHS = 12
PF_EQUITY_SHARE_OF_BASE = 0.25   # 자기자본 = 기본비용 × 이 비율(가정)
PF_LOAN_SPREAD = 0.02            # 기업대출 신규취급 금리에 얹는 PF 가산(가정)
PF_REGION = "강남"

_BREAKEVEN_LAND_MAX_WON_M2 = 200_000_000.0   # 손익분기 토지단가 이분 탐색 상한
_BREAKEVEN_ITERATIONS = 80

# `refi_test` 의 implausible 신호가 **이 조립에서는 켜질 수 없는 이유**. 신호가 늘
# 꺼져 있는 것을 "정상"으로 읽으면, 나중에 대출을 밖에서 주입하는 경로가 생겼을 때
# 그 침묵이 검증된 것인 줄 알게 된다 — 침묵의 근거를 산출물에 적어 둔다.
IMPLAUSIBLE_UNREACHABLE_NOTE = (
    f"이 조립에서 implausible 신호는 구조적으로 켜지지 않는다. 대출을 "
    f"max_loan 의 삼중 제약으로만 만들기 때문이다 — 결속 조건에 따라 max_rate 가 "
    f"cap÷(DSCR {DSCR_MIN}×LTV {LTV_MAX}) · 대출금리 · DY하한÷DSCR "
    f"({DEBT_YIELD_MIN}/{DSCR_MIN} = {DEBT_YIELD_MIN / DSCR_MIN:.6f}) 중 하나가 "
    f"되는데, cap 게이트 상한 0.12 에서도 최댓값이 "
    f"{0.12 / (DSCR_MIN * LTV_MAX):.4f} 라 신호 문턱 1.0 에 닿지 못한다. 차환 LTV "
    f"쪽도 cap÷(DSCR×금리) ≥ 0.02/{DSCR_MIN} = {0.02 / DSCR_MIN:.4f} 라 문턱 0.01 을 "
    "밑돌지 않는다. 그래도 표시 경로를 두는 것은 대출 금액이 밖에서 들어오는 순간"
    "(대장 승격 뒤 실거래가 기준 대출 등) 신호가 켜질 수 있고, 그때 조용히 "
    "지나가면 안 되기 때문이다 — 이 값이 늘 빈 리스트인 것을 '검증됨'으로 읽지 말 것."
)


# ── 입출력 ───────────────────────────────────────────────────────────────────

def _load(data_dir: Path, name: str) -> dict:
    """데이터 한 종을 읽는다. 없으면 파일명을 짚어 멈춘다(빈 dict 로 대신하지 않는다)."""
    path = data_dir / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"데이터가 없다: {path}. `make collect` 로 수집한 뒤 다시 실행하라"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write(path: Path, payload: dict) -> None:
    """tmp 에 쓰고 rename 한다 — 쓰다 만 JSON 이 남지 않는다.

    `os.replace` 는 같은 파일시스템 안에서 원자적이다. tmp 를 대상 디렉터리
    안에 두는 이유가 그것이다(/tmp 에 쓰면 파일시스템이 갈려 원자성이 깨진다).
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def _warn(message: str) -> None:
    """게이트·신호를 stderr 로 알린다. 산출물에도 같은 문구가 남는다."""
    print(f"[build_out] 경고 — {message}", file=sys.stderr)


# ── 작은 도구 ────────────────────────────────────────────────────────────────

def _last(series: list):
    """계열의 최신 원소. 비었으면 None(빈 계열을 0 으로 읽지 않는다)."""
    return series[-1] if series else None


def _require_same_quarter(where: str, labeled: list) -> str:
    """한 행에 함께 실리는 계열들의 분기 라벨이 같은지 확인하고 그 분기를 돌려준다.

    R-ONE 세 계열(rent_level·vacancy·yield)은 같은 분기를 같은 길이로 오름차순
    제공한다고 **가정**하고 여기서는 위치로만 짝짓는다(`[-1]` 과 `zip`). 한 계열만
    새 분기를 먼저 받거나 중간 한 분기를 거르면 그 가정이 깨지는데, 그때 나오는
    행은 2026Q1 임대료에 2025Q4 공실을 붙인 값이다 — 셋 다 정상 범위 안이라
    물리 게이트도 골든도 잡지 못하고 조용히 틀린다. 그래서 짝지을 때마다
    등식을 확인한다.

    보는 것은 길이가 아니라 **분기 라벨**이다. 계열 길이가 서로 달라도 끝나는
    분기가 같으면 뒤에서 잘라 쓰는 이 조립은 여전히 맞고(`zip` 은 짧은 쪽에서
    멈춘다), 어긋나는 것은 끝이 다를 때다.
    """
    quarters = {name: row["yq"] for name, row in labeled}
    if len(set(quarters.values())) > 1:
        detail = ", ".join(f"{name}={yq}" for name, yq in quarters.items())
        raise RuntimeError(
            f"{where}: 계열의 분기가 어긋난다 — {detail}. 세 계열을 위치로 짝지어 "
            "한 행에 싣는 자리라, 어긋난 채로 두면 서로 다른 분기의 임대료·공실·"
            "소득수익률이 한 분기의 관측처럼 나간다"
        )
    return next(iter(quarters.values()))


def _quarter_end(yq: str) -> date:
    """'2026Q1' → 2026-03-31. 연식 계산의 기준일이다(벽시계를 쓰지 않는다)."""
    year, quarter = int(yq[:4]), int(yq[-1])
    month = quarter * 3
    day = 31 if month in (3, 12) else 30
    return date(year, month, day)


def _age_years(use_apr_day: str, as_of: date):
    """사용승인일(YYYYMMDD) → 기준일까지의 연식. 읽을 수 없으면 None."""
    text = (use_apr_day or "").strip()
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        approved = date(int(text[:4]), int(text[4:6]), int(text[6:]))
    except ValueError:
        return None
    return (as_of - approved).days / 365.25


def _region_codes(seed: dict) -> dict:
    """R-ONE 권역명 → 시드 권역코드 목록. 매핑의 단일 출처는 시드 meta 다.

    여기 다시 적으면 시드가 바뀌었을 때 두 곳이 따로 움직인다 — 권역 이름은
    임대료·cap 을 고르는 키라 어긋나면 다른 권역 수치가 조용히 붙는다.
    """
    out: dict = {name: [] for name in REGIONS}
    for code, region in seed["meta"]["rone_region"].items():
        out.setdefault(region, []).append(code)
    return {name: sorted(codes) for name, codes in out.items()}


def _sgg_to_region(seed: dict) -> dict:
    """실거래 시군구 5자리 → R-ONE 권역. 시드의 `region_def` × `rone_region` 이다."""
    rone_region = seed["meta"]["rone_region"]
    return {sgg: rone_region[code]
            for code, sggs in seed["meta"]["region_def"].items()
            for sgg in sggs}


def _median(values: list):
    return statistics.median(values) if values else None


def _quartiles(values: list):
    """(p25, p75). 표본이 4건 미만이면 (None, None) — 두 점의 내삽은 사분위수가 아니다."""
    if len(values) < 4:
        return None, None
    p25, _, p75 = statistics.quantiles(values, n=4, method="inclusive")
    return p25, p75


def _effective_rent_or_violation(nominal_won: float, rent_free_mo: float, where: str,
                                 violations: list):
    """유효임대료를 만들되, 물리 게이트에 걸리면 그 지점만 None 으로 둔다.

    권역 3종의 최신값과 PF 대표 사업지는 이 함수를 쓰지 않고 `effective_rent` 를
    직접 부른다 — 그쪽은 예외를 그대로 올려 빌드를 멈춰야 하는 자리다.
    """
    try:
        return effective_rent.effective_rent(nominal_won, rent_free_mo)
    except (RuntimeError, ValueError) as exc:
        violations.append({"where": where, "kind": type(exc).__name__,
                           "reason": str(exc)})
        _warn(f"{where}: {exc}")
        return None


# ── market.json ──────────────────────────────────────────────────────────────

def _cap_block(income_series: list) -> dict:
    """`caprate.benchmark` 반환을 그대로 싣고 단위 라벨을 붙인다.

    반환은 `cap_income_based`·`quarters_used`·`caveats` 세 키다(부분집합 검사).
    `quarters_used` 는 % 원값이라 소수로 바꾸지 않는다 — 라벨만 붙인다.
    """
    block = caprate.benchmark(income_series)
    return {
        "cap_income_based": block["cap_income_based"],
        "quarters_used": block["quarters_used"],
        "quarters_used_unit": "%(R-ONE 분기 소득수익률 원값 — 소수가 아니다)",
        "caveats": block["caveats"],
    }


def _rate_block(series: list, unit: str, name: str) -> dict:
    latest = _last(series)
    if latest is None:
        raise ValueError(f"금리 계열 {name} 이 비어 있다 — 최신값을 만들 수 없다")
    return {
        "name": name,
        "unit": unit,
        "latest": {"ym": latest["ym"], "value_pct": latest["value"],
                   "value": latest["value"] / PERCENT},
        "trend_months": [{"ym": r["ym"], "value_pct": r["value"]}
                         for r in series[-TREND_MONTHS:]],
    }


def _reit_anchor_block(reits: dict) -> dict:
    """direct 리츠만 앵커 후보로 올린다(계약 7). 캘리브레이션은 하지 않는다."""
    candidates, excluded = [], []
    for code, row in reits["reits"].items():
        latest = _last(row.get("fin") or [])
        entry = {
            "code": code, "name": row["name"], "holding": row["holding"],
            "office_assets": [{"building_id": a.get("building_id"), "note": a.get("note")}
                              for a in row.get("office_assets") or []],
            "latest_fin": None if latest is None else {
                "basis": latest.get("basis"), "reprt": latest.get("reprt"),
                "revenue_won": latest.get("revenue"), "assets_won": latest.get("assets"),
            },
        }
        if row["holding"] == "direct":
            candidates.append(entry)
        else:
            entry["reason"] = (
                f"holding={row['holding']} — 별도(OFS) 손익의 영업수익이 임대료가 "
                "아니라 자리츠·펀드 배당과 이자다. 임대료 앵커로 쓰면 성격이 다른 "
                "수익을 임대수익으로 읽는다."
            )
            excluded.append(entry)
    return {
        "candidates": candidates,
        "excluded": excluded,
        "calibration_done": False,
        "note": (
            "앵커 **후보 목록**이다. 리츠 실적 임대수익으로 렌트프리·전용률 가정을 "
            "맞추는 캘리브레이션은 이 계획의 범위가 아니라 아직 수행하지 않았다. "
            "보고서 종류(reprt)마다 기간이 달라(사업보고서=연간, 반기·분기=해당 "
            "기간분) 연환산 없이 금액을 나란히 비교하면 안 된다."
        ),
    }


def build_market(rone: dict, rates: dict, reits: dict, seed: dict) -> dict:
    """권역 3종의 유효임대료·공실·cap·금리·스프레드."""
    params = effective_rent.region_params()
    rent_free_meta = params["_meta"]
    region_codes = _region_codes(seed)
    violations: list = []

    treasury = _rate_block(rates["treasury10y"], rates["meta"]["units"]["treasury10y"],
                           "국고채(10년) 월평균 유통수익률")
    treasury_latest = treasury["latest"]["value"]

    regions = {}
    for name in REGIONS:
        src = rone["regions"][name]
        rent_free_mo = params[name]["rent_free_mo"]
        latest_rent = _last(src["rent_level"])
        latest_vac = _last(src["vacancy"])
        latest_yld = _last(src["yield"])
        # 최신 한 분기의 임대료·공실·소득수익률을 한 블록에 싣기 전에 셋이 같은
        # 분기인지 못박는다(권역 3종은 예외를 그대로 올려 빌드를 멈추는 자리다).
        _require_same_quarter(
            f"market.regions.{name}.latest",
            [("rent_level", latest_rent), ("vacancy", latest_vac),
             ("yield", latest_yld)])
        nominal = latest_rent["value"] * THOUSAND_WON      # 계약 1 — 천원 → 원
        # 권역 3종의 최신 유효임대료는 예외를 그대로 올린다(빌드를 멈추는 자리).
        eff = effective_rent.effective_rent(nominal, rent_free_mo)
        cap = _cap_block([q["income"] for q in src["yield"]])

        trend = []
        for rent_row, vac_row, yld_row in zip(
                src["rent_level"][-TREND_QUARTERS:], src["vacancy"][-TREND_QUARTERS:],
                src["yield"][-TREND_QUARTERS:]):
            # 추이도 같은 규약이다 — `zip` 은 위치로만 짝지으므로 행마다 확인한다.
            _require_same_quarter(
                f"market.regions.{name}.trend[{rent_row['yq']}]",
                [("rent_level", rent_row), ("vacancy", vac_row),
                 ("yield", yld_row)])
            nominal_q = rent_row["value"] * THOUSAND_WON
            trend.append({
                "yq": rent_row["yq"],
                "nominal_rent_won_m2_mo": nominal_q,
                "effective_rent_won_m2_mo": _effective_rent_or_violation(
                    nominal_q, rent_free_mo,
                    f"market.regions.{name}.trend[{rent_row['yq']}]", violations),
                "vacancy_pct": vac_row["value"],
                "income_yield_pct": yld_row["income"],
            })

        regions[name] = {
            "rone_region": name,
            "seed_region_codes": region_codes[name],
            "latest_quarter": latest_rent["yq"],
            "rent_level_raw_thousand_won_m2_mo": latest_rent["value"],
            "nominal_rent_won_m2_mo": nominal,
            "rent_free_mo": rent_free_mo,
            "rent_free_meta": rent_free_meta,
            "effective_rent_won_m2_mo": eff,
            "vacancy_pct": latest_vac["value"],
            "vacancy": latest_vac["value"] / PERCENT,
            "cap": cap,
            "spread_vs_treasury10y_bp": (cap["cap_income_based"] - treasury_latest)
                                        * BP_PER_UNIT,
            "spread_note": (
                f"cap 벤치마크 {cap['cap_income_based']:.6f} − 국고채10년 "
                f"{treasury_latest:.6f}({treasury['latest']['ym']}). 부호를 자르지 "
                "않는다 — 음수는 권역 소득수익률이 무위험 장기금리를 밑돈다는 뜻이고, "
                "그 자체가 관측이다."
            ),
            "trend_quarters": trend,
        }

    sub_regions, skipped = {}, []
    for full_name, src in rone.get("sub_regions", {}).items():
        parent = full_name.split(">")[1] if full_name.count(">") >= 1 else None
        yields = src.get("yield") or []
        latest_rent = _last(src.get("rent_level") or [])
        latest_quarter = None if latest_rent is None else latest_rent["yq"]
        if len(yields) < caprate.QUARTERS_PER_YEAR:
            # 계열 전체가 너무 짧다 — cap 만이 아니라 행 자체가 최신 시장을 말하지
            # 못한다(신사는 마지막 관측이 2016Q4 다). 행째로 뺀다.
            skipped.append({
                "name": full_name,
                "kind": "short_series",
                "quarters": len(yields),
                "latest_quarter": latest_quarter,
                "row_dropped": True,
                "reason": (
                    f"소득수익률 계열이 {len(yields)}분기뿐이라 연환산에 필요한 "
                    f"{caprate.QUARTERS_PER_YEAR}분기를 못 채운다. 짧은 계열로 합을 "
                    "내면 4분의 3 짜리 cap 이 나오는데 그 값도 게이트 안(2~12%)이라 "
                    "조용히 통과한다 — benchmark 를 부르기 전에 거른다. 이런 계열은 "
                    "관측 자체가 옛것이라 임대료·공실도 함께 뺀다(행째 제외)."
                ),
            })
            continue
        rent_free_mo = params[parent]["rent_free_mo"] if parent in params else None
        latest_vac = _last(src.get("vacancy") or [])
        nominal = None if latest_rent is None else latest_rent["value"] * THOUSAND_WON
        eff = None
        if nominal is not None and rent_free_mo is not None:
            eff = _effective_rent_or_violation(
                nominal, rent_free_mo, f"market.sub_regions.{full_name}", violations)
        # 하위 상권의 cap 은 게이트에 걸려도 **빌드를 멈추지 않는다**. 권역 3종과
        # 달리 이쪽은 참고 계열이고, GBD 상권 여럿이 하한(2%)에서 0.5%p 안쪽이라
        # R-ONE 한 분기 갱신으로 통째로 죽을 자리다(실측: 서울>강남>도산대로의
        # 2024Q2~2025Q1 창 cap 은 1.4756% 로 하한 미달이었다). cap 한 값만 못 쓰는
        # 것이므로 그 지점만 null 로 두고 사유를 두 곳(gate_violations·
        # sub_regions_cap_skipped)에 남긴 뒤 임대료·공실은 그대로 싣는다.
        cap, cap_reason = None, None
        try:
            cap = _cap_block([q["income"] for q in yields])
        except (RuntimeError, ValueError) as exc:
            cap_reason = str(exc)
            skipped.append({
                "name": full_name,
                "kind": "gate",
                "quarters": len(yields),
                "latest_quarter": latest_quarter,
                "row_dropped": False,
                "reason": (
                    f"cap 벤치마크가 물리 게이트에 걸려 cap 만 비웠다(임대료·공실은 "
                    f"그대로다) — {cap_reason}"
                ),
            })
            violations.append({"where": f"market.sub_regions.{full_name}.cap",
                               "kind": type(exc).__name__, "reason": cap_reason})
            _warn(f"market.sub_regions.{full_name}.cap: {exc}")
        sub_regions[full_name] = {
            "parent_region": parent,
            "latest_quarter": latest_quarter,
            "rent_level_raw_thousand_won_m2_mo": (
                None if latest_rent is None else latest_rent["value"]),
            "nominal_rent_won_m2_mo": nominal,
            "rent_free_mo": rent_free_mo,
            "rent_free_meta": rent_free_meta,
            "effective_rent_won_m2_mo": eff,
            "vacancy_pct": None if latest_vac is None else latest_vac["value"],
            "cap": cap,
            "cap_skipped_reason": cap_reason,
        }

    seoul_src = rone["regions"].get(SEOUL_KEY)
    seoul = None
    if seoul_src:
        latest_rent = _last(seoul_src["rent_level"])
        latest_vac = _last(seoul_src["vacancy"])
        # 서울 계열도 참고용이라 하위 상권과 같은 규칙을 쓴다 — cap 하나 때문에
        # 빌드를 멈추지 않는다(권역 3종만 멈춘다).
        seoul_cap, seoul_cap_reason = None, None
        try:
            seoul_cap = _cap_block([q["income"] for q in seoul_src["yield"]])
        except (RuntimeError, ValueError) as exc:
            seoul_cap_reason = str(exc)
            violations.append({"where": "market.seoul_reference.cap",
                               "kind": type(exc).__name__, "reason": seoul_cap_reason})
            _warn(f"market.seoul_reference.cap: {exc}")
        seoul = {
            "latest_quarter": latest_rent["yq"],
            "nominal_rent_won_m2_mo": latest_rent["value"] * THOUSAND_WON,
            "vacancy_pct": latest_vac["value"],
            "cap": seoul_cap,
            "cap_skipped_reason": seoul_cap_reason,
            "note": (
                "서울 전체 계열은 렌트프리 관행 가정이 권역 3종에만 있어 유효임대료를 "
                "만들지 않았다. 명목·공실·cap 만 참고로 싣는다."
            ),
        }

    return {
        "schema": "cheungwi/market/1",
        "as_of": {
            "rone_collected_at": rone["meta"]["collected_at"],
            "rone_latest_quarter": regions[REGIONS[0]]["latest_quarter"],
            "rates_collected_at": rates["meta"]["collected_at"],
            "rates_latest_month": treasury["latest"]["ym"],
            "reits_collected_at": reits["meta"]["collected_at"],
        },
        "units": {
            "rent": "원/㎡·월(임대면적 기준). R-ONE 원값은 천원/㎡·월이라 ×1000 했다.",
            "vacancy_pct": "%", "vacancy": "소수",
            "cap": "소수 연율(0.04 = 4%)",
            "quarters_used": "%(분기 소득수익률 원값)",
            "spread": "bp(1%p = 100bp)",
            "rates": "연%(value_pct)와 소수(value)를 함께 싣는다",
        },
        "rent_free_assumption": rent_free_meta,
        "regions": regions,
        "seoul_reference": seoul,
        "sub_regions": sub_regions,
        "sub_regions_cap_skipped": skipped,
        "rates": {
            "treasury10y": treasury,
            "cd91": _rate_block(rates["cd91"], rates["meta"]["units"]["cd91"],
                                "CD(91일) 월평균 유통수익률"),
            "loan_corp_new": _rate_block(
                rates["loan_corp_new"], rates["meta"]["units"]["loan_corp_new"],
                "예금은행 기업대출 금리(신규취급액 기준)"),
            "source": rates["meta"]["source"],
        },
        "reit_anchors": _reit_anchor_block(reits),
        "gate_violations": violations,
        "caveats": [
            "유효임대료는 개별 건물의 실측 계약임대료가 아니라 **권역 평균 명목임대료에 "
            "권역 대표 렌트프리 가정을 차감한 추정치**다. 렌트프리 개월 수는 관측치가 "
            "아니라 조정 가능한 가정이고(rent_free_assumption 참조), 리츠 앵커 "
            "캘리브레이션은 아직 하지 않았다.",
            "cap 벤치마크는 R-ONE 표본의 **권역 평균** 소득수익률이다. 개별 건물의 cap 이 "
            "아니고, 산출 방식(평가 기준 순영업소득 ÷ 자산가치)이 이 엔진의 NOI 정의와 "
            "달라 실거래 역산 cap 과 나란히 놓고 괴리를 봐야 한다.",
            "권역 명칭은 R-ONE 기준이고 시드의 CBD·GBD·YBD 매핑은 근사다 — 여의도마포는 "
            "마포를 포함한 합성 권역이라 여의도 단독 지표가 아니다.",
            "스프레드는 권역 cap 에서 국고채 10년을 뺀 값이다. 두 수치의 관측 시점이 "
            "다르다(cap 은 분기, 금리는 월).",
            "R-ONE 캐시는 무효화가 없다 — 새 분기를 받으려면 data/raw/rone_office/ 를 "
            "지우고 다시 수집해야 한다. 여기 실린 최신 분기가 곧 데이터층의 한계다.",
        ],
    }


# ── underwriting.json ────────────────────────────────────────────────────────

def _underwrite_one(eff_rent_won: float, gfa_m2: float, age_years: float,
                    vacancy: float, cap: float, loan_rate: float,
                    market_rate: float) -> dict:
    """대장이 있는 한 동의 전 수치 흐름. 보정 → NOI → 가치 → 대출 → 보유 → 차환."""
    adjust = effective_rent.building_adjust(eff_rent_won, age_years, gfa_m2,
                                            DIST_SUBWAY_M)
    result = noi_mod.noi(adjust["value"], gfa_m2, EFFICIENCY, vacancy, OPEX_RATIO)
    noi_won_y = result["noi_won_y"]
    appraised = value.appraise(noi_won_y, cap)
    loan = max_loan(noi_won_y, appraised, LTV_MAX, DSCR_MIN, DEBT_YIELD_MIN, loan_rate)
    hold = hold_model(appraised, loan["loan_won"], loan_rate, noi_won_y,
                      NOI_GROWTH_Y, cap, HOLD_YEARS, ACQ_COST_RATE)
    refi_result = refi.refi_test(noi_won_y, loan["loan_won"], appraised,
                                 DSCR_MIN, REFI_LTV_MAX, market_rate)
    breakeven = refi.breakeven_vacancy(adjust["value"], gfa_m2, EFFICIENCY, OPEX_RATIO,
                                       loan["loan_won"], loan_rate, DSCR_MIN)
    full_egi = adjust["value"] * gfa_m2 * EFFICIENCY * 12
    return {
        "dist_subway_m": DIST_SUBWAY_M,
        "age_years": age_years,
        "gfa_m2": gfa_m2,
        "building_adjust": adjust,
        "noi": result,
        "cap_used": cap,
        "value_won": appraised,
        "loan": loan,
        "hold": {
            "equity_irr": hold["equity_irr"],
            "exit_value_won": hold["exit_value"],
            "cashflows_q": hold["cashflows_q"],
            "assumptions": hold["assumptions"],
        },
        "refi": refi_result,
        "breakeven_vacancy": breakeven,
        "breakeven_context": {
            "required_noi_won_y": DSCR_MIN * loan["loan_won"] * loan_rate,
            "full_occupancy_egi_won_y": full_egi,
            "note": (
                "손익분기 공실률은 float 하나라 가정 봉투가 없다 — 필요 NOI(요구 DSCR × "
                "대출 × 금리)와 만실 EGI(유효임대료 × 임대면적 × 12)를 함께 싣는다. "
                "0 은 '정확히 만실에서 겨우 맞는다'와 '만실이어도 불가하다'가 겹친 값이다."
            ),
        },
    }


def build_underwriting(buildings: dict, seed: dict, market: dict) -> dict:
    """시드 55동 언더라이팅. `ledger` 가 null 이면 권역 수치만 싣는다(계약 3)."""
    rone_region = seed["meta"]["rone_region"]
    seed_by_id = {b["id"]: b for b in seed["buildings"]}
    as_of = _quarter_end(market["as_of"]["rone_latest_quarter"])
    loan_rate = market["rates"]["loan_corp_new"]["latest"]["value"]
    market_rate = loan_rate

    rows, errors, implausible = [], [], []
    for src in buildings["buildings"]:
        region_code = src["region"]
        if region_code not in rone_region:
            raise ValueError(
                f"{src['id']}: 권역코드 {region_code!r} 가 시드의 rone_region 매핑에 "
                f"없다({sorted(rone_region)}). 임대료·cap 을 고르는 키라 임의로 "
                "고르면 다른 권역 수치가 조용히 붙는다"
            )
        region_name = rone_region[region_code]
        region = market["regions"][region_name]
        seed_row = seed_by_id.get(src["id"], {})
        vworld = src.get("vworld") or {}

        row = {
            "id": src["id"],
            "name": src["name"],
            "region_code": region_code,
            "region": region_name,
            "sgg_cd": src.get("sgg_cd"),
            "umd": src.get("umd"),
            "jibun": src.get("jibun"),
            "address_road": seed_row.get("address_road"),
            "region_figures": {
                "latest_quarter": region["latest_quarter"],
                "nominal_rent_won_m2_mo": region["nominal_rent_won_m2_mo"],
                "effective_rent_won_m2_mo": region["effective_rent_won_m2_mo"],
                "rent_free_mo": region["rent_free_mo"],
                "rent_free_meta": region["rent_free_meta"],
                "vacancy": region["vacancy"],
                "cap_income_based": region["cap"]["cap_income_based"],
            },
            "land": {
                "land_price_won_m2": vworld.get("land_price_won_m2"),
                "land_price_year": vworld.get("land_price_year"),
                "zones": vworld.get("zones"),
                "pnu": vworld.get("pnu"),
                "lat": vworld.get("lat"),
                "lon": vworld.get("lon"),
            },
            "ledger_flags": src.get("flags") or [],
        }

        ledger = src.get("ledger")
        gfa = (ledger or {}).get("totArea") or 0.0
        age = _age_years((ledger or {}).get("useAprDay", ""), as_of)
        # 계약 3 — 대장이 없거나 연면적·사용승인일을 못 읽으면 여기서 멈춘다.
        # `building_adjust`·`noi` 에 None 이 들어가면 맨 TypeError 로 죽는다.
        if not ledger or gfa <= 0 or age is None:
            row["pending_ledger"] = True
            row["pending_reason"] = (
                "건축물대장(ledger)이 없어 연면적·사용승인일을 모른다 — 건물 특성 보정과 "
                "NOI 이하를 계산하지 않는다. 대장 부재를 권역 평균이나 0 으로 메우면 "
                "추정이 아니라 지어낸 값이 되므로, 권역 수치만 싣고 자리를 비워 둔다. "
                "data.go.kr 건축물대장 활용신청이 승인된 뒤 재수집·재실행하면 승격된다."
                if not ledger else
                f"대장은 있으나 연면적({gfa})·사용승인일"
                f"({(ledger or {}).get('useAprDay')!r})을 수치로 읽을 수 없다."
            )
            row["blocked"] = ["building_adjust", "noi", "value", "max_loan",
                              "hold_model", "refi_test", "breakeven_vacancy"]
            rows.append(row)
            continue

        row["pending_ledger"] = False
        row["ledger"] = ledger
        try:
            row["underwriting"] = _underwrite_one(
                region["effective_rent_won_m2_mo"], gfa, age, region["vacancy"],
                region["cap"]["cap_income_based"], loan_rate, market_rate)
        except NotImplementedError as exc:      # 계산 불가 — 입력을 고쳐도 안 된다
            _record_failure(row, errors, "NotImplementedError", exc)
        except RuntimeError as exc:             # 물리 게이트 — 단위를 의심하라
            _record_failure(row, errors, "RuntimeError", exc)
        except ValueError as exc:               # 입력이 물리적으로 말이 안 된다
            _record_failure(row, errors, "ValueError", exc)
        else:
            # `implausible` 은 예외를 던지지도 판정을 바꾸지도 않는 신호라, 읽는
            # 쪽이 없으면 아무 일도 일어나지 않는다. **이 조립에서는 구조적으로
            # 켜지지 않는다**(사유는 IMPLAUSIBLE_UNREACHABLE_NOTE) — 그래도 경로를
            # 두는 것은 대출 금액이 밖에서 들어오는 순간(대장 승격 뒤 실거래가
            # 기준 대출 등) 켜질 수 있고, 그때 조용히 지나가면 안 되기 때문이다.
            signal = row["underwriting"]["refi"]
            if signal["implausible"]:
                implausible.append({
                    "id": src["id"], "name": src["name"],
                    "reasons": signal["implausible_reasons"],
                })
                _warn(f"{src['id']} 차환 implausible 신호 — "
                      f"{' / '.join(signal['implausible_reasons'])}")
        rows.append(row)

    pending = sum(1 for r in rows if r["pending_ledger"])
    by_region = {}
    for name in REGIONS:
        group = [r for r in rows if r["region"] == name]
        by_region[name] = {
            "n": len(group),
            "pending_ledger": sum(1 for r in group if r["pending_ledger"]),
            "effective_rent_won_m2_mo":
                market["regions"][name]["effective_rent_won_m2_mo"],
            "vacancy": market["regions"][name]["vacancy"],
            "cap_income_based": market["regions"][name]["cap"]["cap_income_based"],
        }

    return {
        "schema": "cheungwi/underwriting/1",
        "as_of": {
            "buildings_collected_at": buildings["meta"]["collected_at"],
            "seed_as_of": seed["meta"].get("as_of"),
            "rone_latest_quarter": market["as_of"]["rone_latest_quarter"],
            "age_reference_date": as_of.isoformat(),
            "rates_latest_month": market["as_of"]["rates_latest_month"],
        },
        "assumptions": {
            "efficiency": EFFICIENCY,
            "opex_ratio": OPEX_RATIO,
            "ltv_max": LTV_MAX,
            "dscr_min": DSCR_MIN,
            "debt_yield_min": DEBT_YIELD_MIN,
            "refi_ltv_max": REFI_LTV_MAX,
            "loan_rate": loan_rate,
            "market_rate": market_rate,
            "noi_growth_y": NOI_GROWTH_Y,
            "hold_years": HOLD_YEARS,
            "cost_rate": ACQ_COST_RATE,
            "dist_subway_m": DIST_SUBWAY_M,
            "notes": [
                f"대출금리·차환 시장금리는 ECOS 예금은행 기업대출(신규취급액) "
                f"{market['as_of']['rates_latest_month']} 값 {loan_rate:.4f} 을 그대로 "
                "썼다. 실제 부동산 담보대출 금리는 주선·약정 수수료와 스프레드가 붙어 "
                "이보다 높다.",
                "LTV 한도·요구 DSCR·DY 하한은 시장 관행 수준의 가정이며 대주 심사 "
                "결과가 아니다. 넷 중 하나만 흔들려도 대출가능액이 두 자릿수 퍼센트로 "
                "움직인다.",
                "역까지 거리를 담은 데이터층이 없어 dist_subway_m 은 None 이다 — "
                "역세권 계수 1.0 은 '역세권 아님'이 아니라 **판단 유보**다.",
                "진입 cap 과 매각 cap 을 같은 권역 벤치마크로 두었다. 벌리면(cap "
                "expansion) 지분 IRR 이 급격히 나빠지므로 단일 IRR 을 인용하지 말 것.",
            ],
        },
        "summary": {
            "n": len(rows),
            "pending_ledger": pending,
            "underwritten": len(rows) - pending,
            "by_region": by_region,
            "ledger_status": buildings["meta"].get("ledger_status"),
        },
        "buildings": rows,
        "errors": errors,
        "errors_note": (
            "건물 한 동의 실패는 그 행에 격리하고(underwriting_error) 나머지 동은 계속 "
            "계산한다 — 한 동 때문에 쉰네 동을 잃지 않으면서, 빠진 자리가 이름과 사유를 "
            "갖게 하려는 것이다. kind 는 잡은 예외 유형 그대로다: NotImplementedError"
            "(계산 불가) · RuntimeError(물리 게이트 — 단위 의심) · ValueError(입력 오류). "
            "NotImplementedError 는 RuntimeError 의 하위형이라 반드시 먼저 잡는다."
        ),
        "implausible_refi": implausible,
        "implausible_refi_note": IMPLAUSIBLE_UNREACHABLE_NOTE,
        "caveats": [
            "**건축물대장이 열리기 전이라 대부분(또는 전부)의 동이 pending_ledger 다.** "
            "빈 자리를 권역 평균으로 메우지 않았다 — 추정과 부재를 같은 색으로 칠하면 "
            "대장이 없다는 사실이 산출물에서 사라진다.",
            "임대료는 건물 실측이 아니라 권역 지표에 연식·규모·역세권 세 계수를 곱으로 "
            "겹친 추정이다. 특성 간 상관을 무시했으므로 셋이 함께 좋은 건물은 프리미엄이 "
            "과대평가된다.",
            "가치는 직접환원법(NOI ÷ cap) 한 줄이다. 임대차 만기 구조·리스업·CapEx 의 "
            "시점이 들어 있지 않고, 추정가치와 실거래의 오차 분포는 대장 승격 뒤에야 "
            "낼 수 있다(trades_analysis.value_error_dist 참조).",
            "대출은 선순위 한 트랜치·IO(이자만 상환) 가정이다. 원리금균등이면 대출가능액이 "
            "이보다 작아지고, 메자닌·후순위를 얹는 구조는 이 삼중 제약으로 설명되지 않는다.",
            "차환 판정의 `pass` 는 금리와 LTV **두 관문의 AND** 다. 등호는 금리 쪽이 "
            "실패(여유 0), LTV 쪽이 통과(한도 준수)로 갈려, 취득 시점에 DSCR 결속으로 "
            "승인된 대출이 같은 금리의 차환에서는 부결될 수 있다.",
        ],
    }


def _record_failure(row: dict, errors: list, kind: str, exc: Exception) -> None:
    """한 동의 실패를 행과 최상위에 함께 남긴다(조용히 빼지 않는다)."""
    row["underwriting_error"] = {"kind": kind, "reason": str(exc)}
    errors.append({"id": row["id"], "name": row["name"], "kind": kind,
                   "reason": str(exc)})
    _warn(f"{row['id']} 언더라이팅 실패({kind}) — {exc}")


# ── trades_analysis.json ─────────────────────────────────────────────────────

def _year_rows(rows: list) -> list:
    """연도별 중위 평당가. 오래된 → 최신 순서로 고정한다(멱등)."""
    by_year: dict = {}
    for row in rows:
        by_year.setdefault(int(row["deal_ymd"][:4]), []).append(row["per_m2_won"])
    out = []
    for year in sorted(by_year):
        prices = sorted(by_year[year])
        median_m2 = _median(prices)
        p25, p75 = _quartiles(prices)
        out.append({
            "year": year,
            "n": len(prices),
            "median_won_per_m2": median_m2,
            "median_won_per_pyeong": median_m2 * PYEONG_M2,
            "p25_won_per_pyeong": None if p25 is None else p25 * PYEONG_M2,
            "p75_won_per_pyeong": None if p75 is None else p75 * PYEONG_M2,
        })
    return out


def build_trades_analysis(trades: dict, seed: dict) -> dict:
    """해제 제외 실거래의 권역별·연도별 중위 평당가와 매칭 사다리(계약 5·6)."""
    all_rows = trades["trades"]
    canceled = [r for r in all_rows if r.get("canceled")]
    live = [r for r in all_rows if not r.get("canceled")]     # 계약 5
    sgg_to_region = _sgg_to_region(seed)

    def is_exact(row):
        m = row.get("match")
        return bool(m) and not m.get("masked") and len(m.get("candidates") or []) == 1

    exact_all = [r for r in all_rows if is_exact(r)]
    exact_live = [r for r in exact_all if not r.get("canceled")]
    resolved = [r for r in all_rows if (r.get("match") or {}).get("building_id")]
    ambiguous = [r for r in all_rows
                 if r.get("match") and not r["match"].get("building_id")]
    matched = [r for r in all_rows if r.get("match")]
    # **세 수는 배타적이지 않다.** exact ⊆ resolved 다(마스킹이 없고 후보가 하나면
    # 수집기가 그 동을 building_id 로 확정한다). 세 수를 그대로 더하면 exact 를 두 번
    # 세어 matched 를 넘는다 — 배타 합을 쓰려면 resolved_only 를 써야 한다.
    resolved_only = [r for r in resolved if not is_exact(r)]

    by_region = {}
    for name in REGIONS:
        codes = sorted(c for c, r in sgg_to_region.items() if r == name)
        group = [r for r in live if sgg_to_region.get(r["sgg_cd"]) == name]
        by_region[name] = {
            "sgg_cd": codes,
            "n": len(group),
            "by_year": _year_rows(group),
        }
    unmapped = sorted({r["sgg_cd"] for r in live if r["sgg_cd"] not in sgg_to_region})

    by_building: dict = {}
    for row in exact_live:
        bid = row["match"]["candidates"][0]
        by_building.setdefault(bid, []).append(row["per_m2_won"])
    building_rows = [
        {"building_id": bid, "n": len(prices),
         "median_won_per_m2": _median(sorted(prices)),
         "median_won_per_pyeong": _median(sorted(prices)) * PYEONG_M2}
        for bid, prices in sorted(by_building.items())
    ]

    cases = [
        {
            "building_id": row["match"]["candidates"][0],
            "deal_ymd": row["deal_ymd"],
            "sgg_cd": row["sgg_cd"],
            "umd": row["umd"],
            "jibun": row["jibun_masked"],
            "amount_won": row["amount_won"],
            "building_ar_m2": row["building_ar_m2"],
            "per_m2_won": row["per_m2_won"],
            "per_pyeong_won": row["per_m2_won"] * PYEONG_M2,
            "floor": row.get("floor"),
            "build_year": row.get("build_year"),
            "share_deal": row.get("share_deal"),
            "dealing_gbn": row.get("dealing_gbn"),
        }
        for row in sorted(exact_live, key=lambda r: (r["deal_ymd"], r["umd"],
                                                     r["per_m2_won"]))
    ]

    return {
        "schema": "cheungwi/trades_analysis/1",
        "as_of": {
            "trades_collected_at": trades["meta"]["collected_at"],
            "months": trades["meta"].get("months"),
            "seed_as_of": seed["meta"].get("as_of"),
        },
        "units": {
            "per_m2_won": "원/㎡(거래면적 기준)",
            "per_pyeong_won": f"원/평 — 1평 = 400/121 ㎡ = {PYEONG_M2!r}",
            "amount_won": "원",
        },
        "filters": {
            "rows_total": len(all_rows),
            "rows_used": len(live),
            "canceled_excluded": len(canceled),
            "use": "업무(수집 단계에서 이미 업무용만 담겨 있다)",
            "note": (
                "해제(canceled=true) 거래는 데이터층이 지우지 않고 플래그로 보존한다 — "
                "취소된 계약도 그 시점의 호가 정보이기 때문이다. 가격 집계에서 빼는 "
                "판단은 분석 단계의 몫이고, 여기서 뺐다."
            ),
        },
        "region_mapping": {
            "map": dict(sorted(sgg_to_region.items())),
            "source": "seed_buildings.meta.region_def × seed_buildings.meta.rone_region",
            "unmapped_sgg_cd": unmapped,
            "caveat": (
                "시군구 → R-ONE 권역 매핑은 근사다. 여의도마포는 마포(11440)를 포함한 "
                "합성 권역인데 실거래 표본에는 영등포구(11560)만 있어 마포 쪽이 통째로 "
                "빠져 있다. 권역 안의 상권 편차도 이 한 칸으로 뭉개진다."
            ),
        },
        "by_region": by_region,
        "by_building_exact": building_rows,
        "exact_cases": cases,
        "matching": {
            "n_matched": len(matched),
            "nesting": (
                "**exact ⊆ resolved 다 — 세 수를 그대로 더하면 안 된다.** 마스킹이 "
                "없고 후보가 하나인 행은 수집기가 building_id 로 확정하므로 exact 는 "
                "resolved 안에 들어 있다. 사다리를 그리려면 배타적인 세 칸"
                "(ladder_exclusive)을 쓰라 — exact + resolved_only + ambiguous 가 "
                "matched 와 정확히 같다."
            ),
            "ladder_exclusive": {
                "exact": len(exact_all),
                "resolved_only": len(resolved_only),
                "ambiguous": len(ambiguous),
                "sum": len(exact_all) + len(resolved_only) + len(ambiguous),
                "n_matched": len(matched),
            },
            "exact": {
                "n": len(exact_all),
                "n_live": len(exact_live),
                "n_canceled_excluded": len(exact_all) - len(exact_live),
                "parcel_confirmed": True,
                "subset_of_resolved": True,
                "label": ("마스킹 없는 지번이 시드 한 동에만 걸린 행 — 필지까지 "
                          "확정됐다. resolved 의 부분집합이다."),
            },
            "resolved": {
                "n": len(resolved),
                "n_live": sum(1 for r in resolved if not r.get("canceled")),
                "n_canceled_excluded": sum(1 for r in resolved if r.get("canceled")),
                "n_resolved_only": len(resolved_only),
                "n_resolved_only_live": sum(1 for r in resolved_only
                                            if not r.get("canceled")),
                "includes_exact": True,
                "parcel_confirmed": False,
                "label": (
                    "building_id 가 채워진 행 전체다. **이 중 exact "
                    f"{len(exact_all)}행은 마스킹이 없어 필지까지 확정된 행이고**, "
                    f"나머지 {len(resolved_only)}행(n_resolved_only)이 '시드 55동 "
                    "목록 안에서 후보가 유일'할 뿐인 행이다 — 그쪽은 마스킹된 지번이라 "
                    "같은 법정동의 비-시드 건물과 구분되지 않으므로 '확정'으로 읽으면 "
                    "안 된다. parcel_confirmed 는 n_resolved_only 부분에 대한 라벨이다."
                ),
                "excluded_from_aggregation": False,
                "reason": (
                    "권역·연도 집계는 시군구로만 가르므로 매칭 상태와 무관하게 전 행을 "
                    "쓴다. 건물 단위 집계(by_building_exact)에는 exact 만 넣는다."
                ),
            },
            "ambiguous": {
                "n": len(ambiguous),
                "n_live": sum(1 for r in ambiguous if not r.get("canceled")),
                "n_canceled_excluded": sum(1 for r in ambiguous if r.get("canceled")),
                "parcel_confirmed": False,
                "label": "마스킹된 지번이 여러 시드에 동시에 걸려 동을 특정하지 못한 행.",
                "excluded_from_aggregation": True,
                "reason": (
                    "후보 중 첫 동을 고르면 수천 행이 엉뚱한 한 동에 몰린다. 건물 단위 "
                    "집계에서 통째로 뺀다 — 권역·연도 집계에는 시군구만 쓰므로 그대로 남는다."
                ),
            },
            "build_year_conflicts": trades["meta"].get("match_build_year_conflicts", {}),
            "build_year_conflicts_note": (
                "붙은 거래의 건축년도가 갈리는 시드다 — 마스킹 지번이 같은 법정동의 다른 "
                "건물을 끌어왔거나 그 자리를 헐고 다시 지은 것이다. 어느 쪽이든 build_year "
                "로 갈라 보기 전에는 그 시드 매칭을 쓸 수 없다."
            ),
        },
        "value_error_dist": None,
        "value_error_dist_reason": (
            "추정가치 대비 오차 분포는 건물별 추정가치가 있어야 낼 수 있는데, 건축물대장이 "
            "열리지 않아 연면적을 몰라 55동 전부 pending_ledger 다(underwriting.json 참조). "
            "대장 승격 뒤 exact 57행(해제 제외)과 짝을 지어 value.error_dist 로 낸다. "
            "지금 값을 지어내지 않는다."
        ),
        "caveats": [
            "거래면적(building_ar_m2)은 집합건물 거래의 계약·분양면적이라 건물 연면적이 "
            "아니다. 평당가는 그 면적 기준이므로 연면적 기준 단가와 직접 비교하면 안 된다.",
            "공유지분 거래(share_deal)와 층·향·전용률 차이를 나누지 않고 한 칸에 넣었다 — "
            "중위값이 그 편차를 뭉갠다.",
            "표본은 시군구 다섯 곳(종로·중구·영등포·서초·강남)의 업무용 매매다. 대형 "
            "통매각은 건수가 적어 연도별 중위값이 소형 구분소유 거래에 끌린다.",
            "수집 단계의 평당 단가 게이트(30만~2억원/㎡)를 벗어난 43행은 데이터층에서 이미 "
            "빠졌다. 그 행들은 여기 없다.",
        ],
    }


# ── pf_case.json ─────────────────────────────────────────────────────────────

def _pf_inputs(land_won: float, hard_won: float, loan_rate: float,
               stabilized_noi: float, exit_cap: float) -> dict:
    base_cost = land_won + hard_won * (1 + pf.OPTIONAL_DEFAULTS["soft_cost_ratio"])
    return {
        "land_won": land_won,
        "hard_cost_won": hard_won,
        "months_build": PF_MONTHS_BUILD,
        "equity_won": base_cost * PF_EQUITY_SHARE_OF_BASE,
        "loan_rate": loan_rate,
        "stabilized_noi_won_y": stabilized_noi,
        "lease_up_months": PF_LEASE_UP_MONTHS,
        "exit_cap": exit_cap,
    }


def _breakeven_land_price(hard_won: float, loan_rate: float, stabilized_noi: float,
                          exit_cap: float, plot_m2: float):
    """개발이익이 0 이 되는 토지 단가(원/㎡). 못 찾으면 None.

    토지비가 오르면 총사업비도 자기자본도 함께 오르지만 매각가는 그대로라 개발이익은
    단조 감소한다 — 이분법이 성립한다. 상·하한에서 부호가 같으면 값을 지어내지 않고
    None 을 돌려준다(예: 토지비 0 에서도 이익이 음수인 사업).
    """
    def profit_at(unit_price: float) -> float:
        return pf.pf_model(_pf_inputs(unit_price * plot_m2, hard_won, loan_rate,
                                      stabilized_noi, exit_cap))["profit"]

    lo, hi = 0.0, _BREAKEVEN_LAND_MAX_WON_M2
    if profit_at(lo) <= 0 or profit_at(hi) >= 0:
        return None
    for _ in range(_BREAKEVEN_ITERATIONS):
        mid = (lo + hi) / 2
        if profit_at(mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def build_pf_case(market: dict, buildings: dict, seed: dict) -> dict:
    """대표 가상 사업지 한 건의 월별 스케줄과 스트레스 15행."""
    region = market["regions"][PF_REGION]
    eff_rent = region["effective_rent_won_m2_mo"]
    exit_cap = region["cap"]["cap_income_based"]
    # 두 소수의 합이라 부동소수 꼬리가 붙는다(0.0427 + 0.02 = 0.06269999…).
    # 금리는 소수점 여섯째 자리면 1e-4bp 라 표기 단위 밑이다 — 그 자리에서 끊는다.
    loan_rate = round(
        market["rates"]["loan_corp_new"]["latest"]["value"] + PF_LOAN_SPREAD, 6)

    above_ground_m2 = PF_PLOT_M2 * PF_FAR
    gfa_m2 = above_ground_m2 * (1 + PF_BASEMENT_RATIO)
    land_won = PF_LAND_PRICE_WON_M2 * PF_PLOT_M2
    hard_won = PF_HARD_COST_WON_M2 * gfa_m2

    noi_block = noi_mod.noi(eff_rent, gfa_m2, EFFICIENCY, region["vacancy"], OPEX_RATIO)
    stabilized_noi = noi_block["noi_won_y"]

    inputs = _pf_inputs(land_won, hard_won, loan_rate, stabilized_noi, exit_cap)
    model = pf.pf_model(inputs)
    # 게이트 위반이면 예외를 그대로 올린다 — 빠진 행은 "괜찮았다"로 읽힌다.
    stress_rows = pf.stress(inputs)

    code_by_region = {v: k for k, v in seed["meta"]["rone_region"].items()}
    region_code = code_by_region[PF_REGION]
    land_prices = sorted(b["vworld"]["land_price_won_m2"] for b in buildings["buildings"]
                         if b["region"] == region_code
                         and (b.get("vworld") or {}).get("land_price_won_m2"))
    breakeven = _breakeven_land_price(hard_won, loan_rate, stabilized_noi, exit_cap,
                                      PF_PLOT_M2)

    return {
        "schema": "cheungwi/pf_case/1",
        "as_of": {
            "rone_latest_quarter": market["as_of"]["rone_latest_quarter"],
            "rates_latest_month": market["as_of"]["rates_latest_month"],
            "buildings_collected_at": buildings["meta"]["collected_at"],
        },
        "case": {
            "name": "강남권 중형 오피스 신축(가상 사업지)",
            "region": PF_REGION,
            "hypothetical": True,
            "spec": {
                "plot_m2": PF_PLOT_M2,
                "far": PF_FAR,
                "above_ground_m2": above_ground_m2,
                "basement_ratio": PF_BASEMENT_RATIO,
                "gfa_m2": gfa_m2,
                "land_price_won_m2": PF_LAND_PRICE_WON_M2,
                "hard_cost_won_m2": PF_HARD_COST_WON_M2,
                "equity_share_of_base_cost": PF_EQUITY_SHARE_OF_BASE,
            },
            "inputs": inputs,
            "noi_derivation": noi_block,
            "parameter_sources": [
                {"parameter": "stabilized_noi_won_y", "kind": "실측",
                 "source": f"R-ONE 강남 {region['latest_quarter']} 임대료 "
                           f"{region['rent_level_raw_thousand_won_m2_mo']}천원/㎡·월 → "
                           f"×1000 후 렌트프리 {region['rent_free_mo']}개월 차감 → "
                           f"유효 {eff_rent:,.1f}원/㎡·월, 공실 {region['vacancy']:.6f}, "
                           f"전용률 {EFFICIENCY}·운영경비율 {OPEX_RATIO} 로 NOI 산출",
                 "value": stabilized_noi},
                {"parameter": "exit_cap", "kind": "실측",
                 "source": f"R-ONE 강남 소득수익률 최근 4분기 합 "
                           f"{region['cap']['quarters_used']}% ÷ 100",
                 "value": exit_cap},
                {"parameter": "loan_rate", "kind": "실측",
                 "source": f"ECOS 예금은행 기업대출(신규취급액) "
                           f"{market['as_of']['rates_latest_month']} "
                           f"{market['rates']['loan_corp_new']['latest']['value_pct']}% "
                           f"+ PF 가산 {PF_LOAN_SPREAD:.2%}(가산은 가정)",
                 "value": loan_rate},
                {"parameter": "land_price_won_m2", "kind": "가정",
                 "source": "강남권 이면부 중형 개발부지 토지 단가 가정. 시드 55동은 "
                           "프라임 대로변 표본이라 그 개별공시지가를 신규 개발부지의 "
                           "매입 원가로 쓸 수 없다 — land_price_context 참조.",
                 "value": PF_LAND_PRICE_WON_M2},
                {"parameter": "hard_cost_won_m2", "kind": "가정",
                 "source": f"중형 오피스 도급 공사비 단가 가정(약 "
                           f"{PF_HARD_COST_WON_M2 * PYEONG_M2:,.0f}원/평). 프라임 "
                           "커튼월 사양이면 이보다 높다 — 이 사업의 이익은 낙관 쪽이다.",
                 "value": PF_HARD_COST_WON_M2},
                {"parameter": "plot_m2 · far · basement_ratio", "kind": "가정",
                 "source": "일반상업지역 용적률 상한 수준의 중형 개발 규모 가정. "
                           "건축물대장이 열리지 않아 시드 55동의 실측 규모 분포를 "
                           "쓸 수 없다.",
                 "value": [PF_PLOT_M2, PF_FAR, PF_BASEMENT_RATIO]},
                {"parameter": "months_build · lease_up_months", "kind": "가정",
                 "source": "중형 오피스 공사 30개월·임대안정화 12개월 가정.",
                 "value": [PF_MONTHS_BUILD, PF_LEASE_UP_MONTHS]},
                {"parameter": "equity_share_of_base_cost", "kind": "가정",
                 "source": "자기자본 = 기본비용 × 25% 가정. 제도 단계(5~20%)별 변화는 "
                           "스트레스 표의 자기자본 사다리가 따로 낸다.",
                 "value": PF_EQUITY_SHARE_OF_BASE},
            ],
        },
        "land_price_context": {
            "assumed_land_price_won_m2": PF_LAND_PRICE_WON_M2,
            "breakeven_land_price_won_m2": breakeven,
            "seed_land_price_won_m2": {
                "region_code": region_code,
                "n": len(land_prices),
                "min": land_prices[0] if land_prices else None,
                "median": _median(land_prices),
                "max": land_prices[-1] if land_prices else None,
                "source": "VWorld 개별공시지가(시드 건물의 대표 필지)",
            },
            "note": (
                "**시드 55동의 개별공시지가로는 이 사업이 서지 않는다.** 시드는 3대 권역의 "
                "프라임 타워 표본이라 그 필지의 공시지가가 강남권 토지 원가의 상단이고, "
                "이 엔진의 가치(권역 평균 임대료 × R-ONE 소득수익률)로 환산한 완성 자산이 "
                "그 원가를 덮지 못한다. 손익분기 토지 단가를 함께 실어 그 거리를 그대로 "
                "보인다 — 대표 사업지의 토지 단가는 실측이 아니라 가정이다."
            ),
        },
        "model": {
            "total_cost": model["total_cost"],
            "loan_won": model["loan_won"],
            "ltc": model["ltc"],
            "interest_won": model["interest_won"],
            "fee_won": model["fee_won"],
            "exit_value": model["exit_value"],
            "profit": model["profit"],
            "margin": model["margin"],
            "llcr": model["llcr"],
            "llcr_noi_only": model["assumptions"]["llcr_noi_only"],
            "llcr_note": (
                "LLCR 은 두 값을 함께 읽어야 한다(D8). llcr 은 잔여 NOI 와 매각대금의 "
                "준공시점 현재가치를 대출원금으로 나눈 값이라 분자의 대부분이 매각가이고, "
                "커버리지 배수라기보다 exit-LTV 의 역수처럼 움직인다. llcr_noi_only 는 "
                "잔존가치를 뺀 대주 관행에 가까운 값이지만 유한 horizon 이라 1 을 크게 "
                "밑돈다. 하나만 인용하지 말 것."
            ),
            "equity_irr": model["equity_irr"],
            "cashflows_q": model["cashflows_q"],
            "monthly": model["monthly"],
            "assumptions": model["assumptions"],
        },
        "stress": {
            "n": len(stress_rows),
            "rows": stress_rows,
            "llcr_note": (
                "스트레스 각 행의 llcr 은 **매각대금을 포함한 값 하나**다 — 기준 시나리오만 "
                "llcr_noi_only 를 함께 낸다(model.llcr_noi_only). 두 지표의 뜻이 다르므로 "
                "행 사이 비교는 같은 정의끼리만 하라."
            ),
            "note": (
                "delta 는 기준 대비 지분 IRR 의 차이(연율 소수)이고, 어느 한쪽이 None 이면 "
                "None 이다. equity_irr 이 None 인 행은 현금흐름에 부호 변화가 없거나 근이 "
                "탐색 범위 밖이라는 뜻이지 '0%' 가 아니다. 시나리오가 물리 게이트 밖으로 "
                "나가면 그 행을 빼지 않고 예외를 올린다 — 빠진 행은 '괜찮았다'로 읽힌다."
            ),
        },
        "caveats": [
            "**가상 사업지다.** 실제 인허가 건이 아니라 강남권 중형 오피스의 전형적인 규모·"
            "기간 가정에 시장 실측 앵커(임대료·공실·cap·금리)를 물린 것이다. 어떤 파라미터가 "
            "실측이고 어떤 것이 가정인지는 case.parameter_sources 가 갈라 둔다.",
            "분양(선분양 수입)이 없는 임대형 개발 모델이다 — 준공 전 수입이 한 푼도 없다고 "
            "본다. 분양대금으로 공사비를 충당하는 사업에는 그대로 쓸 수 없다.",
            "취득세·보존등기·분담금·예비비·임대차 수수료(TI/LC)·CapEx·법인세·매각비용이 "
            "전부 빠져 있다. 간접비율 하나로 뭉갠 값이라 실제 총사업비는 이보다 크다.",
            "안정화 NOI 는 권역 평균 임대료에서 나온 추정이다. 신축 프라임은 권역 평균보다 "
            "높은 임대료를 받으므로 이 NOI 는 보수적인 쪽이고, 반대로 전용률 0.5 가정은 "
            "지하 주차장까지 임대면적의 밑으로 세는 단순화라 낙관 쪽이다. 두 방향이 섞여 "
            "있으니 순효과를 단정하지 말 것.",
            "exit cap 을 권역 소득수익률 벤치마크로 두었다. 매각가 = NOI ÷ cap 이라 cap "
            "0.5%p 가 매각가를 10% 안팎으로 움직인다 — 단일 시나리오의 profit·IRR 은 "
            "스트레스 표와 함께가 아니면 인용하지 말 것.",
        ],
    }


# ── 조립 ─────────────────────────────────────────────────────────────────────

def build_all(data_dir=None, out_dir=None) -> dict:
    """네 산출물을 만들어 `out_dir` 에 쓴다. 반환은 같은 payload 들이다.

    **조립을 모두 끝낸 뒤에 쓴다.** 중간에 예외가 나면 파일을 한 개도 건드리지
    않으므로 기존 `out/` 이 그대로 남는다. 쓰기 자체는 tmp → `os.replace` 라
    쓰다 만 JSON 도 남지 않는다.
    """
    data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    out_dir = Path(out_dir) if out_dir else DEFAULT_OUT_DIR

    src = {name: _load(data_dir, name) for name in DATA_FILES}

    market = build_market(src["rone_office"], src["rates"], src["reits"],
                          src["seed_buildings"])
    underwriting = build_underwriting(src["buildings"], src["seed_buildings"], market)
    trades_analysis = build_trades_analysis(src["trades"], src["seed_buildings"])
    pf_case = build_pf_case(market, src["buildings"], src["seed_buildings"])

    payloads = {
        "market": market,
        "underwriting": underwriting,
        "trades_analysis": trades_analysis,
        "pf_case": pf_case,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in zip(OUT_FILES, payloads.values()):
        _atomic_write(out_dir / name, payload)
    return payloads


def _summary(payloads: dict) -> str:
    market, uw = payloads["market"], payloads["underwriting"]
    trades, pf_case = payloads["trades_analysis"], payloads["pf_case"]
    lines = [f"== market ({market['as_of']['rone_latest_quarter']} · "
             f"금리 {market['as_of']['rates_latest_month']}) =="]
    for name in REGIONS:
        r = market["regions"][name]
        lines.append(
            f"  {name:6s} 유효임대료 {r['effective_rent_won_m2_mo']:>10,.0f}원/㎡·월 · "
            f"공실 {r['vacancy_pct']:>5.2f}% · cap {r['cap']['cap_income_based']:.4%} · "
            f"스프레드 {r['spread_vs_treasury10y_bp']:>+8.1f}bp")
    lines.append(f"  하위 상권 {len(market['sub_regions'])}곳 · cap 미산출 "
                 f"{len(market['sub_regions_cap_skipped'])}곳 · 게이트 위반 "
                 f"{len(market['gate_violations'])}건")
    lines.append(f"== underwriting == {uw['summary']['n']}동 중 pending_ledger "
                 f"{uw['summary']['pending_ledger']}동 · 언더라이팅 "
                 f"{uw['summary']['underwritten']}동 · 실패 {len(uw['errors'])}건 · "
                 f"implausible {len(uw['implausible_refi'])}건")
    ladder = trades["matching"]["ladder_exclusive"]
    lines.append(f"== trades == {trades['filters']['rows_total']}행 중 해제 "
                 f"{trades['filters']['canceled_excluded']}행 제외 → "
                 f"{trades['filters']['rows_used']}행")
    # 배타적 세 칸으로 적는다 — exact 는 resolved 의 부분집합이라 셋을 나란히
    # 더하면 exact 를 두 번 센다.
    lines.append(f"  매칭 {ladder['n_matched']}행 = exact {ladder['exact']}"
                 f"(해제 제외 {trades['matching']['exact']['n_live']}) + resolved_only "
                 f"{ladder['resolved_only']} + ambiguous {ladder['ambiguous']} "
                 f"(resolved {trades['matching']['resolved']['n']} 은 exact 를 포함한다)")
    for name in REGIONS:
        years = trades["by_region"][name]["by_year"]
        latest = years[-1] if years else None
        if latest:
            lines.append(f"  {name:6s} {latest['year']}년 중위 평당가 "
                         f"{latest['median_won_per_pyeong']:>12,.0f}원 (n={latest['n']})")
    model = pf_case["model"]
    irr = "None" if model["equity_irr"] is None else f"{model['equity_irr']:.4%}"
    lines.append(f"== pf_case == 총사업비 {model['total_cost'] / 1e8:,.1f}억 · LTC "
                 f"{model['ltc']:.4f} · 개발이익 {model['profit'] / 1e8:,.1f}억 · margin "
                 f"{model['margin']:.2%} · equity IRR {irr} · LLCR {model['llcr']:.4f}"
                 f"(NOI만 {model['llcr_noi_only']:.4f}) · 스트레스 "
                 f"{pf_case['stress']['n']}행")
    return "\n".join(lines)


def main() -> int:
    payloads = build_all()
    print(_summary(payloads))
    for name in OUT_FILES:
        print(f"  wrote {DEFAULT_OUT_DIR / name}")
    violations = payloads["market"]["gate_violations"]
    errors = payloads["underwriting"]["errors"]
    implausible = payloads["underwriting"]["implausible_refi"]
    if violations or errors or implausible:
        print(f"주의: 게이트 위반 {len(violations)}건 · 언더라이팅 실패 {len(errors)}건 · "
              f"차환 implausible {len(implausible)}건 — 산출물의 gate_violations·errors·"
              "implausible_refi 를 확인하라", file=sys.stderr)
    print("COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
