from src.collect import common


def test_sido_and_seoul_gu():
    assert common.SIDO["11"] == "서울"
    assert len(common.SEOUL_GU) == 25
    assert common.SEOUL_GU["11680"] == "강남구"
    assert common.SEOUL_GU["11560"] == "영등포구"


def test_load_config_reads_root_config(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text('{"service_key": "X"}')
    monkeypatch.setattr(common, "ROOT", tmp_path)
    assert common.load_config()["service_key"] == "X"


def test_call_with_backoff_retries_5xx_only(monkeypatch):
    monkeypatch.setattr(common.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        return (500, "err") if calls["n"] < 3 else (200, "ok")

    assert common.call_with_backoff(flaky) == (200, "ok")
    assert calls["n"] == 3

    calls["n"] = 0

    def denied():
        calls["n"] += 1
        return (403, "SERVICE_ACCESS_DENIED")

    status, text = common.call_with_backoff(denied)
    assert status == 403 and calls["n"] == 1  # 4xx는 재시도 금지
