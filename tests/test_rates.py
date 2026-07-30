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


def test_parse_ecos_skips_uncastable_values():
    # 결측월은 DATA_VALUE 가 빈 문자열이나 '-' 로 온다 — 0.0 으로 뭉개지 말고 행째로 버린다
    series = parse_ecos(_payload([
        {"TIME": "202601", "DATA_VALUE": "3.12"},
        {"TIME": "202602", "DATA_VALUE": ""},
        {"TIME": "202603", "DATA_VALUE": "-"},
        {"TIME": "202604", "DATA_VALUE": None},
        {"TIME": "2026", "DATA_VALUE": "3.5"},
        {"TIME": "202605", "DATA_VALUE": "3.44"},
    ]))
    assert series == [{"ym": "2026-01", "value": 3.12}, {"ym": "2026-05", "value": 3.44}]


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
