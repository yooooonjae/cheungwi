"""적용기 build_out 테스트 — 합성 data_dir 주입으로 스키마·분기·계약을 고정한다.

엔진 모듈들은 순수 함수라 각자의 골든이 값을 지킨다. 여기서 지키는 것은 **엔진을
실데이터에 붙이는 자리의 규약**이다. 선행 태스크들이 리뷰에서 못박은 계약이 여섯 있고,
그 여섯이 깨지는 방향은 전부 "조용히 틀린 숫자가 나간다"이다.

| # | 계약                                                        | 깨지면                                    |
|---|-------------------------------------------------------------|-------------------------------------------|
| 1 | rent_level 은 천원/㎡·월 — ×1000 후 쓴다                     | 임대료가 1000분의 1 이 되어 게이트에 걸린다 |
| 2 | 임대료 수치에 `region_params()["_meta"]` 동봉               | 렌트프리 가정 라벨 없는 임대료가 출고된다  |
| 3 | ledger=null 은 building_adjust·noi 에 **도달하지 않는다**    | `gfa_m2=None` 이 맨 TypeError 로 죽는다    |
| 4 | `benchmark` 호출 전 4분기 미만 계열을 거른다                 | ValueError 로 빌드가 통째로 죽는다         |
| 5 | `canceled=true` 는 가격 집계 전에 거른다                     | 해제된 계약이 중위 평당가를 흔든다         |
| 6 | `match_exact` 만 필지 확정 · `match_resolved` 는 시드 내 유일 | 734행이 "확정"으로 읽힌다                  |

합성 fixture 는 실파일의 축약형이다 — 구조(키 이름·중첩·단위)는 계약 문서와 같게 두고
행 수만 줄였다. 실데이터로 다시 확인하는 것은 `make analyze` 의 몫이다.

숫자는 손계산으로 확정한다.

| ID        | 입력                                        | 산식                          | 기대값        |
|-----------|---------------------------------------------|-------------------------------|---------------|
| G-BLD-001 | rent_level 30.0천원/㎡·월, 도심 렌트프리 2개월 | 30.0×1000×(12−2)/12          | 25,000.0      |
| G-BLD-002 | 분기 소득수익률 [9.9, 1.0, 1.0, 1.0, 1.0]%   | 뒤 4개 합 4.0% ÷ 100         | 0.04          |
| G-BLD-003 | cap 0.04, 국고채10y 4.0%                     | (0.04 − 0.04) × 10,000       | 0.0bp         |
| G-BLD-004 | 평당가 = 원/㎡ × 400/121                     | 3,000,000 × 3.30578512…      | 9,917,355.37… |

G-BLD-002 의 첫 분기 9.9% 는 "뒤 4개만 합한다"를 고정하는 미끼다. 다섯 개를 다
합하면 0.139 가 되어 cap 게이트(0.02~0.12) 밖이라 RuntimeError 로 죽는다.
"""

import json
import math
from pathlib import Path

import pytest

from src.analysis import build_out
from src.analysis.build_out import build_all
from src.analysis.effective_rent import region_params


PYEONG_M2 = 400 / 121

FILES = {"market.json", "underwriting.json", "trades_analysis.json", "pf_case.json"}


# ── 합성 데이터 6종 ──────────────────────────────────────────────────────────

def _quarters(n: int, start_year: int = 2025) -> list:
    """오래된 → 최신 순서의 분기 라벨. R-ONE 수집기와 같은 오름차순이다."""
    out = []
    y, q = start_year, 1
    for _ in range(n):
        out.append(f"{y}Q{q}")
        q += 1
        if q > 4:
            y, q = y + 1, 1
    return out


def _series(yqs: list, values: list) -> list:
    return [{"yq": yq, "value": v} for yq, v in zip(yqs, values)]


def _rone(tmp: Path) -> None:
    """R-ONE 축약형.

    권역 3종은 5분기다. 하위 상권 셋으로 세 경로를 모두 태운다 — 정상(광화문)·
    4분기 미만(신사, 계약 4)·cap 게이트 위반(도산대로, 소득수익률 0.1%×4 → cap
    0.004 로 하한 0.02 미달).
    """
    yqs = _quarters(5)
    # 소득수익률 첫 분기 9.9% 는 '뒤 4개만 합한다'를 고정하는 미끼다(G-BLD-002).
    incomes = [9.9, 1.0, 1.0, 1.0, 1.0]

    def region(rent, vac, income_pct=None):
        series = income_pct or incomes
        return {
            "rent_index": _series(yqs, [100.0] * 5),
            "vacancy": _series(yqs, [vac] * 5),
            "rent_level": _series(yqs, [rent] * 5),
            "yield": [{"yq": yq, "income": inc, "capital": 0.5, "total": inc + 0.5}
                      for yq, inc in zip(yqs, series)],
        }

    payload = {
        "regions": {
            "도심": region(30.0, 6.0),
            "강남": region(28.0, 5.0),
            "여의도마포": region(20.0, 4.0),
            "서울": region(25.0, 5.0),
        },
        "sub_regions": {
            "서울>도심>광화문": region(35.0, 5.0),
            # 게이트 미끼 — 분기 0.1% 넷의 합 0.4% → cap 0.004 는 하한 0.02 밖이다.
            # 실측에서도 서울>강남>도산대로는 2024Q2~2025Q1 창에서 1.4756% 였다.
            "서울>강남>도산대로": region(24.0, 5.0, [0.1] * 5),
            # 2분기짜리 계열 — benchmark 는 4분기 미만이면 ValueError 다(계약 4).
            "서울>강남>신사": {
                "rent_index": _series(yqs[:2], [100.0, 100.0]),
                "vacancy": _series(yqs[:2], [5.0, 5.0]),
                "rent_level": _series(yqs[:2], [19.0, 19.0]),
                "yield": [{"yq": yq, "income": 1.0, "capital": 0.5, "total": 1.5}
                          for yq in yqs[:2]],
            },
        },
        "meta": {
            "collected_at": "2026-07-30",
            "units": {"rent_level": "천원/㎡(임대면적 기준 월 임대료)",
                      "vacancy": "%", "yield": "%(분기)"},
            "source": "한국부동산원 R-ONE 상업용부동산 임대동향조사",
        },
    }
    (tmp / "rone_office.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _rates(tmp: Path) -> None:
    months = [f"2025-{m:02d}" for m in range(1, 13)] + ["2026-01"]
    payload = {
        "treasury10y": [{"ym": m, "value": 4.0} for m in months],
        "cd91": [{"ym": m, "value": 3.0} for m in months],
        "loan_corp_new": [{"ym": m, "value": 5.0} for m in months],
        "meta": {"collected_at": "2026-07-30", "source": "한국은행 ECOS",
                 "units": {"treasury10y": "연%", "cd91": "연%",
                           "loan_corp_new": "연리%"}},
    }
    (tmp / "rates.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _seed(tmp: Path) -> None:
    payload = {
        "buildings": [
            {"id": "a-tower", "name": "가타워", "region": "CBD", "sgg_cd": "11140",
             "umd": "장교동", "jibun": "1", "address_road": "서울 중구 청계천로 86"},
            {"id": "b-tower", "name": "나타워", "region": "GBD", "sgg_cd": "11680",
             "umd": "역삼동", "jibun": "737", "address_road": "서울 강남구 테헤란로 152"},
        ],
        "meta": {"rone_region": {"CBD": "도심", "GBD": "강남", "YBD": "여의도마포"},
                 "region_def": {"CBD": ["11110", "11140"], "GBD": ["11680", "11650"],
                                "YBD": ["11560"]},
                 "rone_region_caveat": "R-ONE 상권 경계와 1:1이 아닌 근사 매핑",
                 "as_of": "2026-07-30"},
    }
    (tmp / "seed_buildings.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _buildings(tmp: Path, with_ledger: bool = True) -> None:
    """한 동은 대장 null(계약 3), 한 동은 대장 있음(승격 경로)."""
    ledger = {
        "mgmBldrgstPk": "11680-100", "bldNm": "나타워", "dongNm": "",
        "totArea": 60_000.0, "archArea": 3_000.0, "platArea": 5_000.0,
        "grndFlrCnt": 20, "ugrndFlrCnt": 5, "heit": 90.0,
        "useAprDay": "20100301", "mainPurpsCdNm": "업무시설", "etcPurps": "",
        "vlRat": 800.0, "bcRat": 60.0, "parking": 300, "hoCnt": 0,
    } if with_ledger else None
    payload = {
        "buildings": [
            {"id": "a-tower", "name": "가타워", "region": "CBD", "sgg_cd": "11140",
             "umd": "장교동", "jibun": "1", "ledger": None, "ledger_dong_count": None,
             "match_method": None, "flags": ["대장 미조회: HTTP 403"],
             "vworld": {"lat": 37.5, "lon": 127.0, "zones": ["일반상업지역"],
                        "pnu": "1114010700100010000", "land_price_won_m2": 50_000_000,
                        "land_price_year": "2025"}},
            {"id": "b-tower", "name": "나타워", "region": "GBD", "sgg_cd": "11680",
             "umd": "역삼동", "jibun": "737", "ledger": ledger, "ledger_dong_count": 1,
             "match_method": "alias", "flags": [],
             "vworld": {"lat": 37.5, "lon": 127.03, "zones": ["일반상업지역"],
                        "pnu": "1168010100107370000", "land_price_won_m2": 70_000_000,
                        "land_price_year": "2025"}},
        ],
        "meta": {"collected_at": "2026-07-30", "total": 2, "matched": 1 if with_ledger else 0,
                 "source": "국토부 건축물대장 표제부 + VWorld",
                 "ledger_status": "" if with_ledger else "HTTP 403"},
    }
    (tmp / "buildings.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _trade(ymd, sgg, umd, per_m2, *, canceled=False, match=None, amount=1_000_000_000,
           area=100.0, build_year=2000):
    return {"sgg_cd": sgg, "umd": umd, "jibun_masked": "7**", "use": "업무",
            "building_type": "집합", "deal_ymd": ymd, "amount_won": amount,
            "building_ar_m2": area, "plottage_ar_m2": None, "floor": 5,
            "build_year": build_year, "per_m2_won": per_m2, "dealing_gbn": "중개거래",
            "sler": "법인", "buyer": "법인", "canceled": canceled, "share_deal": False,
            "match": match}


def _trades(tmp: Path) -> None:
    exact = {"building_id": "b-tower", "kind": "jibun_only", "area_ratio": None,
             "masked": False, "candidates": ["b-tower"]}
    resolved = {"building_id": "b-tower", "kind": "jibun_only", "area_ratio": None,
                "masked": True, "candidates": ["b-tower"]}
    ambiguous = {"building_id": None, "kind": "jibun_only", "area_ratio": None,
                 "masked": True, "candidates": ["a-tower", "b-tower"]}
    rows = [
        # 도심 2024년 — 살아 있는 두 건의 중위는 3,000,000원/㎡ 다.
        _trade("2024-03-01", "11140", "장교동", 2_000_000),
        _trade("2024-06-01", "11140", "장교동", 4_000_000),
        # 해제 거래. 살려 두면 중위가 4,000,000 으로 밀린다(계약 5).
        _trade("2024-09-01", "11140", "장교동", 90_000_000, canceled=True),
        _trade("2025-03-01", "11680", "역삼동", 5_000_000, match=exact),
        _trade("2025-04-01", "11680", "역삼동", 6_000_000, match=resolved),
        _trade("2025-05-01", "11680", "역삼동", 7_000_000, match=ambiguous),
        _trade("2025-06-01", "11560", "여의도동", 3_000_000),
    ]
    payload = {"trades": rows, "meta": {
        "collected_at": "2026-07-30", "n_office": len(rows), "canceled": 1,
        "matched": 3, "match_resolved": 2, "match_ambiguous": 1, "match_exact": 1,
        "months": "200601~202607", "complete": True, "ledger_ready": False,
        "source": "국토부 RTMS 상업업무용",
        "sgg_list": ["11110", "11140", "11560", "11650", "11680"]}}
    (tmp / "trades.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _reits(tmp: Path) -> None:
    payload = {"reits": {
        "417310": {"name": "코람코더원리츠", "corp_code": "01", "holding": "direct",
                   "office_assets": [{"building_id": "b-tower", "note": "직접 보유"}],
                   "fin": [{"year": 2026, "reprt": "11011", "assets": 5.0e11,
                            "liab": 1.0e11, "equity": 4.0e11, "revenue": 8.5e9,
                            "basis": "2026-02-28", "basis_raw": "2026.02.28 현재"}],
                   "div": [{"stlm_dt": "2026-02-28", "total_div": 4371.0,
                            "yld": 1.6, "dps": 73.0}]},
        "334890": {"name": "이지스밸류리츠", "corp_code": "02", "holding": "indirect",
                   "office_assets": [{"building_id": "a-tower", "note": "자리츠 지분"}],
                   "fin": [{"year": 2026, "reprt": "11011", "assets": 3.0e11,
                            "liab": 1.0e11, "equity": 2.0e11, "revenue": 4.4e9,
                            "basis": "2026-02-28", "basis_raw": "2026.02.28 현재"}],
                   "div": []},
    }, "meta": {"collected_at": "2026-07-30", "source": "OpenDART",
                "holdings": {"direct": 1, "indirect": 1, "mixed": 0}}}
    (tmp / "reits.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    _rone(d), _rates(d), _seed(d), _buildings(d), _trades(d), _reits(d)
    return d


@pytest.fixture
def built(tmp_path, data_dir):
    out_dir = tmp_path / "out"
    payloads = build_all(data_dir=data_dir, out_dir=out_dir)
    return payloads, out_dir


def _read(out_dir: Path, name: str) -> dict:
    return json.loads((out_dir / name).read_text(encoding="utf-8"))


# ── 브리프가 요구한 테스트 셋 ────────────────────────────────────────────────

def test_build_all_produces_four_files(tmp_path, data_dir):
    build_all(data_dir=data_dir, out_dir=tmp_path / "out")
    assert {p.name for p in (tmp_path / "out").iterdir()} == FILES


def test_underwriting_pending_ledger_when_null(built):
    _, out_dir = built
    rows = {r["id"]: r for r in _read(out_dir, "underwriting.json")["buildings"]}

    pending = rows["a-tower"]
    assert pending["pending_ledger"] is True
    # 계약 3 — 대장이 없으면 건물 보정·NOI 이하가 **아예 없다**(빈 값이 아니라 부재).
    assert "underwriting" not in pending
    assert pending["pending_reason"]
    assert "building_adjust" in pending["blocked"] and "noi" in pending["blocked"]
    # 권역 수치는 그대로 싣는다.
    assert pending["region_figures"]["effective_rent_won_m2_mo"] == 25_000.0

    done = rows["b-tower"]
    assert done["pending_ledger"] is False
    assert "blocked" not in done
    assert done["underwriting"]["noi"]["noi_won_y"] > 0


def test_trades_analysis_excludes_canceled(built):
    _, out_dir = built
    ta = _read(out_dir, "trades_analysis.json")
    assert ta["filters"]["canceled_excluded"] == 1
    assert ta["filters"]["rows_used"] == ta["filters"]["rows_total"] - 1

    y2024 = {y["year"]: y for y in ta["by_region"]["도심"]["by_year"]}[2024]
    assert y2024["n"] == 2                       # 해제 1건이 빠졌다
    # 살아 있는 두 건 2,000,000·4,000,000 의 중위는 3,000,000원/㎡ 다.
    assert y2024["median_won_per_m2"] == 3_000_000
    assert abs(y2024["median_won_per_pyeong"] - 3_000_000 * PYEONG_M2) < 1e-6


# ── 계약 1·2: 단위 환산과 렌트프리 가정 라벨 ─────────────────────────────────

def test_rent_level_is_converted_from_thousand_won(built):
    """G-BLD-001 — 30.0천원/㎡·월 → 30,000원, 렌트프리 2개월 → 25,000원."""
    _, out_dir = built
    cbd = _read(out_dir, "market.json")["regions"]["도심"]
    assert cbd["rent_level_raw_thousand_won_m2_mo"] == 30.0
    assert cbd["nominal_rent_won_m2_mo"] == 30_000.0
    assert cbd["effective_rent_won_m2_mo"] == 25_000.0
    assert cbd["rent_free_mo"] == 2.0


def test_every_rent_figure_carries_the_rent_free_meta(built):
    """계약 2 — 렌트프리 가정 라벨 없이 임대료를 출고하지 않는다."""
    _, out_dir = built
    market = _read(out_dir, "market.json")
    meta = region_params()["_meta"]
    assert market["rent_free_assumption"] == meta
    for region in market["regions"].values():
        assert region["rent_free_meta"] == meta
    for row in _read(out_dir, "underwriting.json")["buildings"]:
        assert row["region_figures"]["rent_free_meta"] == meta


# ── 계약 4: cap 벤치마크 ─────────────────────────────────────────────────────

def test_cap_benchmark_uses_last_four_quarters_and_keeps_percent_values(built):
    """G-BLD-002 — 뒤 4개(1.0×4)만 합해 0.04. 다섯 개를 다 합하면 게이트 밖이다."""
    _, out_dir = built
    cap = _read(out_dir, "market.json")["regions"]["도심"]["cap"]
    assert abs(cap["cap_income_based"] - 0.04) < 1e-12
    assert cap["quarters_used"] == [1.0, 1.0, 1.0, 1.0]      # % 원값 그대로
    assert cap["caveats"]                                    # 반환 3키 부분집합 검사


def test_short_sub_region_series_is_filtered_with_a_stated_reason(built):
    """4분기 미만 계열(서울>강남>신사 2분기)은 benchmark 를 부르기 전에 거른다."""
    _, out_dir = built
    market = _read(out_dir, "market.json")
    assert "서울>강남>신사" not in market["sub_regions"]
    skipped = {s["name"]: s for s in market["sub_regions_cap_skipped"]}
    assert "서울>강남>신사" in skipped
    assert skipped["서울>강남>신사"]["quarters"] == 2
    assert skipped["서울>강남>신사"]["kind"] == "short_series"
    assert skipped["서울>강남>신사"]["row_dropped"] is True
    assert "4분기" in skipped["서울>강남>신사"]["reason"]
    assert "서울>도심>광화문" in market["sub_regions"]


def test_sub_region_cap_gate_nulls_that_point_and_keeps_the_build(built):
    """하위 상권 cap 이 게이트에 걸려도 빌드는 계속된다 — 그 지점만 null 이다.

    권역 3종과 달리 하위 상권은 참고 계열이고, GBD 상권 여럿이 게이트 하한 2% 에서
    0.5%p 안쪽이라(도산대로 2.3992·교대역 2.3638·신사역 2.4851) R-ONE 한 분기
    갱신에 `make analyze` 전체가 죽을 자리다. 실측으로도 도산대로는 직전 창
    (2024Q2~2025Q1)에서 cap 1.4756% 로 하한을 밑돌았다.
    """
    _, out_dir = built
    market = _read(out_dir, "market.json")

    row = market["sub_regions"]["서울>강남>도산대로"]      # 행은 살아 있다
    assert row["cap"] is None
    assert row["cap_skipped_reason"]
    # cap 만 못 쓰는 것이므로 임대료·공실은 그대로 실린다.
    assert row["nominal_rent_won_m2_mo"] == 24_000.0
    assert row["effective_rent_won_m2_mo"] == 24_000.0 * 10.5 / 12
    assert row["vacancy_pct"] == 5.0

    skipped = {s["name"]: s for s in market["sub_regions_cap_skipped"]}
    assert skipped["서울>강남>도산대로"]["kind"] == "gate"
    assert skipped["서울>강남>도산대로"]["row_dropped"] is False

    # 게이트 위반은 최상위에도 모인다(조용한 통과 금지).
    where = {v["where"]: v for v in market["gate_violations"]}
    assert "market.sub_regions.서울>강남>도산대로.cap" in where
    assert where["market.sub_regions.서울>강남>도산대로.cap"]["kind"] == "RuntimeError"
    # 권역 3종은 멀쩡히 나왔다 — 하위 상권 하나가 빌드를 끌고 내려가지 않는다.
    assert market["regions"]["강남"]["cap"]["cap_income_based"] == 0.04


def test_spread_is_cap_minus_treasury10y(built):
    """G-BLD-003 — cap 4.0% − 국고채10y 4.0% = 0.0bp. 부호를 자르지 않는다."""
    _, out_dir = built
    market = _read(out_dir, "market.json")
    assert market["rates"]["treasury10y"]["latest"]["value_pct"] == 4.0
    for region in market["regions"].values():
        expected = (region["cap"]["cap_income_based"] - 0.04) * 10_000
        assert abs(region["spread_vs_treasury10y_bp"] - expected) < 1e-9


def test_rates_carry_latest_and_twelve_month_trend(built):
    _, out_dir = built
    rates = _read(out_dir, "market.json")["rates"]
    assert set(rates) >= {"treasury10y", "cd91", "loan_corp_new"}
    for key in ("treasury10y", "cd91", "loan_corp_new"):
        assert len(rates[key]["trend_months"]) == 12
        assert rates[key]["trend_months"][-1]["ym"] == rates[key]["latest"]["ym"]


# ── 계약 6: 매칭 사다리 ──────────────────────────────────────────────────────

def test_matching_ladder_labels_resolved_as_seed_unique_not_confirmed(built):
    _, out_dir = built
    m = _read(out_dir, "trades_analysis.json")["matching"]
    assert m["exact"]["n"] == 1 and m["exact"]["parcel_confirmed"] is True
    assert m["resolved"]["parcel_confirmed"] is False
    assert "시드" in m["resolved"]["label"]
    assert m["ambiguous"]["n"] == 1
    assert m["ambiguous"]["excluded_from_aggregation"] is True
    assert m["ambiguous"]["reason"]


def test_matching_ladder_is_not_three_exclusive_buckets(built):
    """exact ⊆ resolved 다 — 세 수를 더하면 exact 를 두 번 센다.

    합성 표본은 exact 1 · resolved 2(exact 포함) · ambiguous 1 이라 단순 합은
    1+2+1 = 4 인데 매칭된 행은 3 이다. 배타적 사다리(1 + 1 + 1)를 따로 낸다.
    """
    _, out_dir = built
    m = _read(out_dir, "trades_analysis.json")["matching"]
    assert m["n_matched"] == 3
    assert m["exact"]["n"] + m["resolved"]["n"] + m["ambiguous"]["n"] == 4  # ≠ 3
    assert m["exact"]["subset_of_resolved"] is True
    assert m["resolved"]["includes_exact"] is True
    assert m["resolved"]["n_resolved_only"] == 1

    ladder = m["ladder_exclusive"]
    assert ladder == {"exact": 1, "resolved_only": 1, "ambiguous": 1,
                      "sum": 3, "n_matched": 3}
    assert ladder["sum"] == ladder["n_matched"] == m["n_matched"]
    assert "더하면 안 된다" in m["nesting"]
    # 해제 제외 수를 세 칸 모두에 병기한다(exact 만 갖고 있으면 비대칭이다).
    for bucket in ("exact", "resolved", "ambiguous"):
        assert m[bucket]["n"] == m[bucket]["n_live"] + m[bucket]["n_canceled_excluded"]


def test_ladder_closes_for_any_mix_of_match_states():
    """사다리 항등식은 표본과 무관하다 — 배타 세 칸의 합이 늘 matched 와 같다.

    (실데이터에서는 57 + 677 + 3,789 = 4,523 이다. 실산출을 읽는 대신 계약대로
    합성 입력으로 고정한다.)
    """
    exact = {"building_id": "b-tower", "masked": False, "candidates": ["b-tower"],
             "kind": "jibun_only", "area_ratio": None}
    resolved = {"building_id": "b-tower", "masked": True, "candidates": ["b-tower"],
                "kind": "jibun_only", "area_ratio": None}
    ambiguous = {"building_id": None, "masked": True, "kind": "jibun_only",
                 "area_ratio": None, "candidates": ["a-tower", "b-tower"]}
    rows = ([_trade("2025-01-01", "11680", "역삼동", 5_000_000, match=exact)] * 3
            + [_trade("2025-02-01", "11680", "역삼동", 6_000_000, match=resolved)] * 5
            + [_trade("2025-03-01", "11680", "역삼동", 7_000_000, match=ambiguous)] * 7
            + [_trade("2025-04-01", "11680", "역삼동", 8_000_000)] * 2)   # 매칭 없음
    seed = {"buildings": [], "meta": {
        "rone_region": {"CBD": "도심", "GBD": "강남", "YBD": "여의도마포"},
        "region_def": {"CBD": ["11140"], "GBD": ["11680"], "YBD": ["11560"]}}}

    m = build_out.build_trades_analysis(
        {"trades": rows, "meta": {"collected_at": "2026-07-30"}}, seed)["matching"]
    assert m["n_matched"] == 15                       # 매칭 없는 2행은 빠진다
    assert m["exact"]["n"] == 3 and m["resolved"]["n"] == 8
    assert m["resolved"]["n_resolved_only"] == 5      # 8 − 3(exact 가 포함돼 있다)
    assert m["ambiguous"]["n"] == 7
    assert m["ladder_exclusive"]["sum"] == m["n_matched"] == 15


def test_exact_cases_are_listed_individually(built):
    _, out_dir = built
    ta = _read(out_dir, "trades_analysis.json")
    assert [c["building_id"] for c in ta["exact_cases"]] == ["b-tower"]
    case = ta["exact_cases"][0]
    assert case["deal_ymd"] == "2025-03-01"
    assert abs(case["per_pyeong_won"] - 5_000_000 * PYEONG_M2) < 1e-6
    # 추정가치 대비 오차는 대장 승격 뒤의 일이다 — 지어내지 않고 사유를 싣는다.
    assert ta["value_error_dist"] is None
    assert ta["value_error_dist_reason"]


def test_pyeong_conversion_is_four_hundred_over_one_twenty_one(built):
    """G-BLD-004 — 1평 = 400/121 ㎡. 3.3 으로 반올림하면 0.17% 어긋난다."""
    _, out_dir = built
    ta = _read(out_dir, "trades_analysis.json")
    y = {r["year"]: r for r in ta["by_region"]["강남"]["by_year"]}[2025]
    assert abs(y["median_won_per_pyeong"] / y["median_won_per_m2"] - 400 / 121) < 1e-12


# ── PF 대표 사업지 ───────────────────────────────────────────────────────────

def test_pf_case_carries_nine_decisions_and_both_llcr_values(built):
    _, out_dir = built
    pf_case = _read(out_dir, "pf_case.json")
    model = pf_case["model"]
    assert len(model["assumptions"]["decisions"]) == 9
    assert "llcr" in model and "llcr_noi_only" in model
    assert model["llcr_noi_only"] == model["assumptions"]["llcr_noi_only"]


def test_pf_case_stress_table_is_complete_and_labels_its_llcr(built):
    _, out_dir = built
    stress = _read(out_dir, "pf_case.json")["stress"]
    assert len(stress["rows"]) == 15          # 시나리오 11 + 자기자본 사다리 4
    assert stress["rows"][0]["name"] == "공사비 +5%"
    for row in stress["rows"]:
        assert set(row) >= {"name", "shock", "delta", "equity_irr", "ltc", "llcr"}
    # 스트레스 행의 llcr 은 매각대금을 포함한 값 하나뿐이다(기준 행만 두 값을 낸다).
    assert "llcr_noi_only" in stress["llcr_note"]


def test_pf_case_exit_cap_stays_inside_the_gate_under_stress(built):
    """스트레스는 게이트 위반을 예외로 올린다 — 대표 사업지 exit cap 이 여유를 가져야 한다."""
    _, out_dir = built
    inputs = _read(out_dir, "pf_case.json")["case"]["inputs"]
    assert inputs["exit_cap"] + 0.01 <= 0.12
    assert inputs["exit_cap"] / 0.9 <= 0.12


def test_pf_case_states_parameter_sources_and_land_price_context(built):
    _, out_dir = built
    case = _read(out_dir, "pf_case.json")["case"]
    kinds = {s["kind"] for s in case["parameter_sources"]}
    assert kinds == {"실측", "가정"}                     # 둘을 섞어 두지 않는다
    for src in case["parameter_sources"]:
        assert src["parameter"] and src["source"]
    ctx = _read(out_dir, "pf_case.json")["land_price_context"]
    assert ctx["breakeven_land_price_won_m2"] > 0
    assert ctx["seed_land_price_won_m2"]["median"] > 0


# ── 원자적 쓰기·멱등 ─────────────────────────────────────────────────────────

def test_rerun_is_byte_identical(tmp_path, data_dir):
    """멱등 — 같은 입력이면 같은 바이트다(벽시계 시각을 싣지 않는다)."""
    out_dir = tmp_path / "out"
    build_all(data_dir=data_dir, out_dir=out_dir)
    first = {n: (out_dir / n).read_bytes() for n in FILES}
    build_all(data_dir=data_dir, out_dir=out_dir)
    assert {n: (out_dir / n).read_bytes() for n in FILES} == first


def test_failed_build_preserves_previous_out(tmp_path, data_dir):
    """부분 실패로 기존 산출을 깨지 않는다 — 조립을 다 끝낸 뒤에 쓴다."""
    out_dir = tmp_path / "out"
    build_all(data_dir=data_dir, out_dir=out_dir)
    good = {n: (out_dir / n).read_bytes() for n in FILES}

    # 임대료를 1000배로 부풀린다 → 유효임대료 물리 게이트 위반.
    rone = json.loads((data_dir / "rone_office.json").read_text(encoding="utf-8"))
    for row in rone["regions"]["도심"]["rent_level"]:
        row["value"] *= 1000
    (data_dir / "rone_office.json").write_text(
        json.dumps(rone, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(RuntimeError):
        build_all(data_dir=data_dir, out_dir=out_dir)
    assert {n: (out_dir / n).read_bytes() for n in FILES} == good
    assert not list(out_dir.glob("*.tmp"))


def test_missing_data_file_names_the_file(tmp_path, data_dir):
    (data_dir / "rates.json").unlink()
    with pytest.raises(FileNotFoundError, match="rates.json"):
        build_all(data_dir=data_dir, out_dir=tmp_path / "out")


# ── 대장이 열린 뒤의 승격 경로 ───────────────────────────────────────────────

def test_underwriting_full_chain_when_ledger_present(built):
    """대장이 있으면 보정→NOI→가치→대출→보유→차환→손익분기까지 간다."""
    _, out_dir = built
    row = {r["id"]: r for r in
           _read(out_dir, "underwriting.json")["buildings"]}["b-tower"]
    u = row["underwriting"]
    assert set(u) >= {"building_adjust", "noi", "value_won", "loan", "hold",
                      "refi", "breakeven_vacancy"}
    # 강남 28.0천원 → 28,000원, 렌트프리 1.5개월 → 24,500원. 연식 16년(1.0)·
    # 연면적 6만㎡(1.04)·역 거리 모름(1.0) → 25,480원/㎡·월.
    assert abs(u["building_adjust"]["value"] - 24_500.0 * 1.04) < 1e-6
    assert u["building_adjust"]["factors"] == {"age": 1.0, "scale": 1.04, "subway": 1.0}
    # NOI = 25,480 × (60,000×0.5) × 12 × (1−0.05) × 0.85
    expected_noi = 25_480.0 * 30_000 * 12 * 0.95 * 0.85
    assert abs(u["noi"]["noi_won_y"] - expected_noi) < 1e-3
    assert abs(u["value_won"] - expected_noi / u["cap_used"]) < 1e-3
    assert u["loan"]["binding"] in {"ltv", "dscr", "debt_yield"}
    assert set(u["refi"]) >= {"pass", "max_rate", "headroom_bp", "implausible"}
    assert 0.0 <= u["breakeven_vacancy"] <= 1.0
    # 역까지 거리를 모른다는 사실이 유보로 남아야 한다(0 이 아니라 판단 보류).
    assert u["dist_subway_m"] is None


def test_two_assumption_shapes_both_survive_serialization(built):
    """`building_adjust` 는 리스트로, `noi` 는 사전으로 가정을 싣는다 — 둘 다 그대로 나간다."""
    _, out_dir = built
    u = {r["id"]: r for r in
         _read(out_dir, "underwriting.json")["buildings"]}["b-tower"]["underwriting"]
    assert isinstance(u["building_adjust"]["assumptions"], list)
    assert all(isinstance(a, str) for a in u["building_adjust"]["assumptions"])
    assert isinstance(u["noi"]["assumptions"], dict)
    assert u["noi"]["assumptions"]["nla_m2"] == 30_000.0
    assert u["building_adjust"]["caveats"] and u["noi"]["assumptions"]["caveats"]


def test_region_mapping_comes_from_the_seed_not_a_local_copy(built):
    """권역 매핑의 단일 출처는 시드 meta 다 — 여기 다시 적으면 두 곳이 따로 움직인다."""
    _, out_dir = built
    market = _read(out_dir, "market.json")
    assert market["regions"]["도심"]["seed_region_codes"] == ["CBD"]
    assert market["regions"]["여의도마포"]["seed_region_codes"] == ["YBD"]
    mapping = _read(out_dir, "trades_analysis.json")["region_mapping"]
    assert mapping["map"] == {"11110": "도심", "11140": "도심",
                              "11650": "강남", "11680": "강남",
                              "11560": "여의도마포"}
    assert mapping["unmapped_sgg_cd"] == []


def test_refi_implausible_signal_is_surfaced_not_swallowed(built):
    """implausible 은 예외를 던지지 않는 신호다 — 사유 문구까지 실어 보낸다."""
    _, out_dir = built
    uw = _read(out_dir, "underwriting.json")
    row = {r["id"]: r for r in uw["buildings"]}["b-tower"]
    refi = row["underwriting"]["refi"]
    assert refi["implausible"] is False
    assert refi["implausible_reasons"] == []
    # 켜진 건은 산출물 최상위에 모아 둔다(조용한 통과 금지).
    assert uw["implausible_refi"] == []
    # 빈 리스트가 '검증됨'으로 읽히지 않도록 침묵의 근거를 함께 싣는다.
    assert "구조적으로 켜지지 않는다" in uw["implausible_refi_note"]


# ── 실패·신호 수집 경로(정상 조립에서는 도달하지 않는 자리) ──────────────────

def test_not_implemented_is_caught_before_runtime_error(tmp_path, data_dir, monkeypatch):
    """`NotImplementedError` 는 `RuntimeError` 의 하위형이라 **먼저** 잡아야 한다.

    순서가 뒤집히면 "계산할 수 없다"는 신호가 "단위를 의심하라"로 오분류되어,
    입력을 고치면 되는 문제처럼 보인다. 이 테스트는 kind 문자열로 그 순서를 읽는다.
    """
    def boom(*_args, **_kwargs):
        raise NotImplementedError("원리금균등(io=False)은 계산하지 않는다")

    monkeypatch.setattr(build_out, "_underwrite_one", boom)
    payloads = build_all(data_dir=data_dir, out_dir=tmp_path / "out")

    errors = payloads["underwriting"]["errors"]
    assert [e["kind"] for e in errors] == ["NotImplementedError"]   # RuntimeError 아님
    assert "io=False" in errors[0]["reason"]


def test_building_failure_is_isolated_and_the_build_continues(tmp_path, data_dir,
                                                             monkeypatch):
    """한 동이 물리 게이트로 죽어도 나머지 동과 나머지 산출물은 그대로 나온다."""
    def boom(*_args, **_kwargs):
        raise RuntimeError("cap 0.900000(= 90.0000%)이 물리 범위[0.02, 0.12] 밖이다")

    monkeypatch.setattr(build_out, "_underwrite_one", boom)
    out_dir = tmp_path / "out"
    payloads = build_all(data_dir=data_dir, out_dir=out_dir)

    assert {p.name for p in out_dir.iterdir()} == FILES      # 빌드는 계속됐다
    uw = payloads["underwriting"]
    rows = {r["id"]: r for r in uw["buildings"]}
    failed = rows["b-tower"]
    assert failed["pending_ledger"] is False
    assert "underwriting" not in failed                     # 반쪽 결과를 남기지 않는다
    assert failed["underwriting_error"]["kind"] == "RuntimeError"
    assert "물리 범위" in failed["underwriting_error"]["reason"]
    # 실패는 행에 격리되고 최상위에도 이름과 사유로 남는다.
    assert [e["id"] for e in uw["errors"]] == ["b-tower"]
    assert uw["errors_note"]
    # 대장이 없어 애초에 계산하지 않는 동은 영향을 받지 않는다.
    assert rows["a-tower"]["pending_ledger"] is True
    assert uw["summary"]["pending_ledger"] == 1


def test_implausible_refi_flows_to_the_top_level_when_it_fires(tmp_path, data_dir,
                                                               monkeypatch):
    """신호가 켜진 결과는 사유 문구와 함께 최상위로 흐른다.

    이 조립에서는 대출을 `max_loan` 의 삼중 제약으로만 만들어 신호가 구조적으로
    켜지지 않는다(DY 하한 0.08 ÷ DSCR 1.3 = 6.15% 가 max_rate 의 바닥이라 문턱
    1.0 에 닿지 못한다). 표시 경로가 살아 있는지는 그래서 주입으로 확인한다.
    """
    real = build_out.refi.refi_test

    def loud(*args, **kwargs):
        result = dict(real(*args, **kwargs))
        result["implausible"] = True
        result["implausible_reasons"] = ["견딜 수 있는 최대금리가 12.00(= 연 1,200%)"]
        return result

    monkeypatch.setattr(build_out.refi, "refi_test", loud)
    payloads = build_all(data_dir=data_dir, out_dir=tmp_path / "out")

    flagged = payloads["underwriting"]["implausible_refi"]
    assert [f["id"] for f in flagged] == ["b-tower"]
    assert flagged[0]["reasons"] == ["견딜 수 있는 최대금리가 12.00(= 연 1,200%)"]
    # 판정을 바꾸지 않는 신호이므로 행의 refi 결과는 그대로 남아 있어야 한다.
    row = {r["id"]: r for r in payloads["underwriting"]["buildings"]}["b-tower"]
    assert row["underwriting"]["refi"]["implausible"] is True


def test_all_pending_when_no_ledger_anywhere(tmp_path, data_dir):
    """실데이터의 현실 — 55동 전부 ledger=null 이면 55동 전부 pending 이다."""
    _buildings(data_dir, with_ledger=False)
    payloads = build_all(data_dir=data_dir, out_dir=tmp_path / "out")
    uw = payloads["underwriting"]
    assert uw["summary"]["pending_ledger"] == uw["summary"]["n"] == 2
    assert uw["summary"]["underwritten"] == 0
    assert all(r["pending_ledger"] for r in uw["buildings"])


# ── 리츠 앵커 ────────────────────────────────────────────────────────────────

def test_only_direct_reits_are_anchor_candidates(built):
    """indirect·mixed 의 revenue 는 임대료가 아니라 배당·이자다."""
    _, out_dir = built
    anchors = _read(out_dir, "market.json")["reit_anchors"]
    assert [c["name"] for c in anchors["candidates"]] == ["코람코더원리츠"]
    assert [e["name"] for e in anchors["excluded"]] == ["이지스밸류리츠"]
    assert anchors["excluded"][0]["holding"] == "indirect"
    assert anchors["excluded"][0]["reason"]
    assert anchors["calibration_done"] is False


# ── 산출물 전체의 정직성 규약 ────────────────────────────────────────────────

def test_every_output_carries_caveats_and_source_stamp(built):
    _, out_dir = built
    for name in FILES:
        payload = _read(out_dir, name)
        assert payload["caveats"], name
        assert payload["as_of"], name
        assert payload["schema"], name


def test_json_is_finite_everywhere(built):
    """NaN·Infinity 는 표준 JSON 이 아니다 — 파서가 다른 하류에서 조용히 깨진다."""
    _, out_dir = built

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, float):
            assert math.isfinite(node), path

    for name in FILES:
        walk(_read(out_dir, name), name)
