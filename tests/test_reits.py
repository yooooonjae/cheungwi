import json

from src.collect.common import ROOT
from src.collect.reits import pick_revenue


def test_seed_reits_refers_valid_buildings():
    seeds = json.load(open(ROOT / "data" / "seed_reits.json"))["reits"]
    assert 8 <= len(seeds) <= 15
    bids = {b["id"] for b in json.load(open(ROOT / "data" / "seed_buildings.json"))["buildings"]}
    for t, r in seeds.items():
        assert t.isalnum() and r["name"]
        for a in r["office_assets"]:
            assert a["building_id"] is None or a["building_id"] in bids


def test_pick_revenue_prefers_operating():
    rows = [{"account_nm": "자산총계", "fs_div": "OFS", "thstrm_amount": "1,000"},
            {"account_nm": "영업수익", "fs_div": "OFS", "thstrm_amount": "52,300,000,000"},
            {"account_nm": "영업수익", "fs_div": "CFS", "thstrm_amount": "99"}]
    assert pick_revenue(rows) == 52_300_000_000.0


def test_pick_revenue_none_when_absent():
    assert pick_revenue([{"account_nm": "자산총계", "fs_div": "OFS", "thstrm_amount": "1"}]) is None
