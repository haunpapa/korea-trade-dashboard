"""exporter 순수 함수 단위 테스트 (네트워크 불필요)."""

import datetime as dt

import pytest

from app.exporter import KST, _next_run, default_yymm, purge_recent_cache, status

pytestmark = pytest.mark.unit


class TestNextRun:
    def test_today_if_future(self):
        now = dt.datetime(2026, 6, 12, 6, 0, tzinfo=KST)
        assert _next_run(now, 7, 30) == dt.datetime(2026, 6, 12, 7, 30, tzinfo=KST)

    def test_tomorrow_if_passed(self):
        now = dt.datetime(2026, 6, 12, 8, 0, tzinfo=KST)
        assert _next_run(now, 7, 30) == dt.datetime(2026, 6, 13, 7, 30, tzinfo=KST)

    def test_exact_time_rolls_to_tomorrow(self):
        now = dt.datetime(2026, 6, 12, 7, 30, tzinfo=KST)
        assert _next_run(now, 7, 30).day == 13


class TestDefaultYymm:
    def test_format(self):
        ym = default_yymm()
        assert len(ym) == 6 and ym.isdigit()
        assert 1 <= int(ym[4:]) <= 12


class TestPurgeRecentCache:
    def test_deletes_only_matching(self, tmp_path):
        class FakeCache:
            cache_dir = tmp_path

        class FakeClient:
            cache = FakeCache()

        (tmp_path / "rows_202605_85.json").write_text("[]")
        (tmp_path / "total_v2_202604.json").write_text("{}")
        (tmp_path / "rows_202501_85.json").write_text("[]")

        n = purge_recent_cache(FakeClient(), ["202605", "202604"])
        assert n == 2
        remaining = [p.name for p in tmp_path.glob("*.json")]
        assert remaining == ["rows_202501_85.json"]


class TestStatus:
    def test_initial_shape(self):
        assert {"enabled", "running", "last_ok", "last_error"} <= set(status)
