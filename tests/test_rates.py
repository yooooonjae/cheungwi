import json

import pytest

from src.collect import rates
from src.collect.common import ROOT
from src.collect.rates import parse_ecos


def test_parse_ecos_monthly_series():
    payload = json.load(open(ROOT / "tests" / "fixtures" / "ecos_rows_sample.json"))
    series = parse_ecos(payload)
    assert series[0] == {"ym": "2026-01", "value": 3.12}
    assert [r["ym"] for r in series] == sorted(r["ym"] for r in series)
    assert all(isinstance(r["value"], float) for r in series)


def test_parse_ecos_empty_result():
    assert parse_ecos({"RESULT": {"CODE": "INFO-200"}}) == []


def _payload(rows):
    return {"StatisticSearch": {"list_total_count": len(rows), "row": rows}}


def test_parse_ecos_skips_uncastable_values_and_sorts():
    # 결측월은 DATA_VALUE 가 빈 문자열이나 '-' 로 온다 — 0.0 으로 뭉개지 말고 행째로 버린다.
    # 입력 행 순서를 일부러 뒤섞어 둔다: 정렬이 빠지면 이 단언이 곧바로 깨진다.
    series = parse_ecos(_payload([
        {"TIME": "202605", "DATA_VALUE": "3.44"},
        {"TIME": "202602", "DATA_VALUE": ""},
        {"TIME": "202512", "DATA_VALUE": "2.98"},
        {"TIME": "202603", "DATA_VALUE": "-"},
        {"TIME": "202601", "DATA_VALUE": "3.12"},
        {"TIME": "202604", "DATA_VALUE": None},
        {"TIME": "2026", "DATA_VALUE": "3.5"},
    ]))
    assert series == [{"ym": "2025-12", "value": 2.98},
                      {"ym": "2026-01", "value": 3.12},
                      {"ym": "2026-05", "value": 3.44}]


def test_fetch_series_refuses_truncated_response(tmp_path, monkeypatch):
    # 받은 행수가 list_total_count 에 못 미치면 절단본을 캐시에 박제하지 않고 실패시킨다
    def fake_page(stat, item, start, end, first, last):
        if first == 1:
            return {"StatisticSearch": {"list_total_count": 138,
                                        "row": [{"TIME": "201501", "DATA_VALUE": "2.5"}]}}
        return {"RESULT": {"CODE": "INFO-200", "MESSAGE": "해당하는 데이터가 없습니다."}}

    monkeypatch.setattr(rates, "RAW_DIR", tmp_path)
    monkeypatch.setattr(rates, "_get_page", fake_page)
    with pytest.raises(RuntimeError, match="절단"):
        rates._fetch_series("treasury10y", "721Y001", "5050000", "201501", "202606")
    assert not (tmp_path / "treasury10y.json").exists()


def _months(n, value=3.0, first=(2015, 1)):
    """2015-01 부터 n개월짜리 정상 계열."""
    y, m, out = first[0], first[1], []
    for _ in range(n):
        out.append({"ym": f"{y:04d}-{m:02d}", "value": value})
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def test_validate_passes_clean_series():
    # 아래 게이트 테스트들이 '무엇이든 걸리는' 게 아님을 보이는 대조군
    assert rates._validate("treasury10y", _months(rates.MIN_MONTHS)) is None


def test_validate_rejects_short_series():
    with pytest.raises(RuntimeError, match="개월 수 부족"):
        rates._validate("treasury10y", _months(rates.MIN_MONTHS - 1))


def test_validate_rejects_out_of_range_value():
    # 금리 계열에 지수·금액이 잘못 실려 오면(단위 혼재) 범위 게이트가 잡는다
    series = _months(rates.MIN_MONTHS)
    series[7]["value"] = 104.2
    with pytest.raises(RuntimeError, match="범위"):
        rates._validate("cd91", series)


def test_validate_rejects_duplicate_month():
    series = _months(rates.MIN_MONTHS)
    series.insert(3, dict(series[2]))  # 같은 달이 두 번 실린 계열
    with pytest.raises(RuntimeError, match="같은 월이 두 번"):
        rates._validate("cd91", series)


def test_validate_rejects_missing_month():
    series = _months(rates.MIN_MONTHS + 1)
    del series[50]  # 중간 한 달이 빠져도 개월 수 하한은 넘는다 — 연속성 게이트가 잡아야 한다
    with pytest.raises(RuntimeError, match="월이 비었다"):
        rates._validate("loan_corp_new", series)


def test_check_item_rejects_foreign_item():
    # 항목코드를 잘못 넘겨 국고채 5년이 섞이면 조용히 평균내지 말고 실패해야 한다
    rows = [{"ITEM_CODE1": "5050000", "TIME": "202601", "DATA_VALUE": "3.1"},
            {"ITEM_CODE1": "5040000", "TIME": "202602", "DATA_VALUE": "2.9"}]
    assert rates._check_item("treasury10y", "5050000", rows[:1]) is None
    with pytest.raises(RuntimeError, match="섞였다"):
        rates._check_item("treasury10y", "5050000", rows)


def test_rows_raises_on_error_result_but_accepts_info_200():
    # 데이터 없음(INFO-200)만 빈 결과로 받아들이고, 키·파라미터 오류는 예외로 드러낸다
    assert rates._rows({"RESULT": {"CODE": "INFO-200"}}, "cd91") == (0, [])
    with pytest.raises(RuntimeError, match="비정상 응답"):
        rates._rows({"RESULT": {"CODE": "INFO-100", "MESSAGE": "인증키가 유효하지 않습니다."}}, "cd91")
