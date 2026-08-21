"""증분 수집(app.incremental) — 기존 data/*.json 의 달은 재사용, 빠진 달만 새로 만든다."""
from __future__ import annotations

import pytest

from app.incremental import label, missing_months, stitch_series, stitch_series_map


def test_label_roundtrip():
    assert label("202607") == "26.07"


def test_missing_months_uses_prior_labels():
    prior = [{"m": "25.06", "exp": 1}, {"m": "25.07", "exp": 2}, {"m": "26.05", "exp": 3}]
    seq = ["202508", "202509", "202605", "202606", "202607"]
    assert missing_months(prior, seq) == ["202508", "202509", "202606", "202607"]


def test_missing_months_all_when_prior_empty():
    assert missing_months(None, ["202606", "202607"]) == ["202606", "202607"]
    assert missing_months([], ["202606"]) == ["202606"]


def test_stitch_series_keeps_window_order_and_drops_old():
    prior = [{"m": "25.06", "exp": 1}, {"m": "25.07", "exp": 2}, {"m": "26.05", "exp": 3}]
    fresh = {"202606": {"m": "26.06", "exp": 4}, "202607": {"m": "26.07", "exp": 5}}
    seq = ["202507", "202605", "202606", "202607"]  # 25.06 은 창 밖
    assert stitch_series(prior, fresh, seq) == [
        {"m": "25.07", "exp": 2}, {"m": "26.05", "exp": 3}, {"m": "26.06", "exp": 4}, {"m": "26.07", "exp": 5},
    ]


def test_stitch_series_fresh_overrides_prior_same_month():
    prior = [{"m": "26.05", "exp": 3}]
    fresh = {"202605": {"m": "26.05", "exp": 30}}
    assert stitch_series(prior, fresh, ["202605"]) == [{"m": "26.05", "exp": 30}]


def test_stitch_series_missing_month_becomes_null_point():
    """prior 에도 fresh 에도 없는 달은 exp=None 포인트로 채워 길이를 보장한다."""
    out = stitch_series([], {}, ["202606"])
    assert out == [{"m": "26.06", "exp": None}]


def test_stitch_series_map_per_key():
    prior = {"IT·반도체": [{"m": "26.05", "exp": 1}], "모빌리티": [{"m": "26.05", "exp": 2}]}
    fresh = {"202606": {"IT·반도체": [{"m": "26.06", "exp": 10}], "모빌리티": [{"m": "26.06", "exp": 20}]}}
    out = stitch_series_map(prior, fresh, ["202605", "202606"], keys=["IT·반도체", "모빌리티"])
    assert out["IT·반도체"] == [{"m": "26.05", "exp": 1}, {"m": "26.06", "exp": 10}]
    assert out["모빌리티"] == [{"m": "26.05", "exp": 2}, {"m": "26.06", "exp": 20}]


def test_stitch_does_not_mutate_inputs():
    prior = [{"m": "26.05", "exp": 3}]
    fresh = {"202606": {"m": "26.06", "exp": 4}}
    stitch_series(prior, fresh, ["202605", "202606"])
    assert prior == [{"m": "26.05", "exp": 3}] and fresh == {"202606": {"m": "26.06", "exp": 4}}


# ---------------------------------------------------------------------------
# collect(prior=...) 오케스트레이션 — 빌더는 monkeypatch, 호출된 (end, months) 만 기록
# ---------------------------------------------------------------------------
def _pt(ym, v):
    return {"m": label(ym), "exp": v}


def _prior_files(months):
    """202506..202605 12개월치 이전 산출물 흉내."""
    from app.mappings import REGION_NAMES, SECTOR_BUCKETS, SECTOR_GROUPS
    return {
        "trend.json": [{**_pt(ym, 1.0), "bal": 0.5} for ym in months],
        "sector-trend.json": {g: [_pt(ym, 2.0) for ym in months] for g in SECTOR_GROUPS},
        "region-trend.json": {r: [_pt(ym, 3.0) for ym in months] for r in REGION_NAMES},
        "item-trend.json": {i: [_pt(ym, 4.0) for ym in months] for i in SECTOR_BUCKETS},
        "fx.json": [{"m": label(ym), "rate": 1300.0} for ym in months],
        "meta.json": {"end_yymm": months[-1], "months": len(months)},
    }


@pytest.fixture
def recorded_builders(monkeypatch):
    """aggregate/fx 빌더를 가짜로 바꾸고 build_trend 계열의 (end, months) 호출을 기록."""
    import app.exporter as ex
    from app.mappings import REGION_NAMES, SECTOR_BUCKETS, SECTOR_GROUPS

    calls: list[tuple[str, str, int]] = []

    async def fake_monthly(client, end, refresh=False):
        return {"end": end}

    async def fake_trend(client, end, months=12, refresh=False):
        calls.append(("trend", end, months))
        from app.aggregate import month_seq
        return [{**_pt(ym, 9.0), "bal": 9.0} for ym in month_seq(end, months)]

    async def fake_sector(client, group, end, months=12, refresh=False):
        calls.append(("sector", end, months))
        from app.aggregate import month_seq
        return [_pt(ym, 8.0) for ym in month_seq(end, months)]

    async def fake_region(client, region, end, months=12, refresh=False):
        calls.append(("region", end, months))
        from app.aggregate import month_seq
        return [_pt(ym, 7.0) for ym in month_seq(end, months)]

    async def fake_items(client, end, months=12, refresh=False):
        calls.append(("item", end, months))
        from app.aggregate import month_seq
        return {i: [_pt(ym, 6.0) for ym in month_seq(end, months)] for i in SECTOR_BUCKETS}

    async def fake_item_countries(client, end, refresh=False):
        return {}

    async def fake_fx(client, end, months=12, refresh=False):
        calls.append(("fx", end, months))
        from app.aggregate import month_seq
        return [{"m": label(ym), "rate": 1400.0} for ym in month_seq(end, months)]

    monkeypatch.setattr(ex.aggregate, "build_monthly", fake_monthly)
    monkeypatch.setattr(ex.aggregate, "build_trend", fake_trend)
    monkeypatch.setattr(ex.aggregate, "build_sector_trend", fake_sector)
    monkeypatch.setattr(ex.aggregate, "build_region_trend", fake_region)
    monkeypatch.setattr(ex.aggregate, "build_item_trends", fake_items)
    monkeypatch.setattr(ex.aggregate, "build_item_countries", fake_item_countries)
    monkeypatch.setattr(ex.fx, "build_fx_trend", fake_fx)
    return calls, ex, SECTOR_GROUPS, REGION_NAMES


async def test_collect_incremental_builds_only_missing_months(recorded_builders):
    calls, ex, groups, regions = recorded_builders
    from app.aggregate import month_seq

    prior_months = month_seq("202605", 12)             # 202506..202605
    prior = _prior_files(prior_months)
    data = await ex.collect(object(), "202607", 12, prior=prior)

    # 빠진 달 = 202606, 202607 만, 각각 months=1
    trend_calls = sorted(c for c in calls if c[0] == "trend")
    assert trend_calls == [("trend", "202606", 1), ("trend", "202607", 1)]
    assert all(c[2] == 1 for c in calls), "증분 모드에서 months=12 전체 빌드가 있으면 안 됨"

    # 창은 202508..202607 12개월, 앞 10개월은 prior 값(1.0), 뒤 2개월은 새 값(9.0)
    trend = data["trend.json"]
    assert [p["m"] for p in trend] == [label(ym) for ym in month_seq("202607", 12)]
    assert [p["exp"] for p in trend] == [1.0] * 10 + [9.0, 9.0]
    assert data["sector-trend.json"][groups[0]][-1] == _pt("202607", 8.0)
    assert data["region-trend.json"][regions[0]][0]["exp"] == 3.0
    assert data["fx.json"][-1]["rate"] == 1400.0
    assert data["meta.json"]["end_yymm"] == "202607" and data["meta.json"]["incremental"] is True


async def test_collect_without_prior_is_full_build(recorded_builders):
    calls, ex, *_ = recorded_builders
    data = await ex.collect(object(), "202607", 12)
    assert ("trend", "202607", 12) in calls
    assert data["meta.json"].get("incremental") is False


async def test_collect_incremental_noop_when_prior_complete(recorded_builders):
    calls, ex, *_ = recorded_builders
    from app.aggregate import month_seq
    prior = _prior_files(month_seq("202607", 12))
    data = await ex.collect(object(), "202607", 12, prior=prior)
    assert [c for c in calls if c[0] == "trend"] == []
    assert data["trend.json"][-1]["exp"] == 1.0


async def test_collect_incremental_refresh_recent_refetches_tail(recorded_builders):
    """refresh_recent=1 이면 prior 에 있어도 창의 마지막 1개월은 다시 빌드한다(잠정→확정 현행화)."""
    calls, ex, *_ = recorded_builders
    from app.aggregate import month_seq
    prior = _prior_files(month_seq("202607", 12))          # 이미 완전
    data = await ex.collect(object(), "202607", 12, prior=prior, refresh_recent=1)
    assert [c for c in calls if c[0] == "trend"] == [("trend", "202607", 1)]
    assert data["trend.json"][-1]["exp"] == 9.0 and data["trend.json"][-2]["exp"] == 1.0


def test_load_prior_reads_outdir_or_none(tmp_path):
    from scripts.export_static import load_prior
    assert load_prior(tmp_path) is None
    (tmp_path / "trend.json").write_text('[{"m":"26.05","exp":1}]', encoding="utf-8")
    (tmp_path / "meta.json").write_text('{"end_yymm":"202605"}', encoding="utf-8")
    prior = load_prior(tmp_path)
    assert prior["trend.json"][0]["m"] == "26.05" and prior["meta.json"]["end_yymm"] == "202605"
    (tmp_path / "trend.json").write_text("not json", encoding="utf-8")
    assert load_prior(tmp_path) is None


def test_months_with_null_field():
    from app.incremental import months_with_null
    fx = [{"m": "26.05", "rate": 1491.8}, {"m": "26.06", "rate": None}, {"m": "26.07", "rate": None}]
    seq = ["202605", "202606", "202607"]
    assert months_with_null(fx, seq, "rate") == ["202606", "202607"]
    assert months_with_null(None, seq, "rate") == []


async def test_collect_incremental_rebuilds_months_with_null_fx(recorded_builders):
    """prior 가 달로는 완전해도 fx rate 가 null 인 달은 재수집한다(EXIM 키 나중 추가 대응)."""
    calls, ex, *_ = recorded_builders
    from app.aggregate import month_seq
    months = month_seq("202607", 12)
    prior = _prior_files(months)
    prior["fx.json"] = [{"m": label(ym), "rate": None if ym in ("202606", "202607") else 1300.0}
                        for ym in months]
    data = await ex.collect(object(), "202607", 12, prior=prior)
    assert sorted(c[1] for c in calls if c[0] == "trend") == ["202606", "202607"]
    assert [p["rate"] for p in data["fx.json"][-2:]] == [1400.0, 1400.0]
