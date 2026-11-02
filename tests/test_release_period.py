"""Requested release periods must never select stale or unrelated announcements."""

import datetime as dt
from pathlib import Path

import pytest

from app.release_source import pick_latest_article


@pytest.mark.parametrize(
    ("kind", "day", "title"),
    [
        ("monthly", "2026-11-01", "2026년10월 수출입동향"),
        ("monthly", "2027-01-04", "2026년 12월 수출입 동향"),
        ("tenday", "2026-10-12", "2026년 10월 1일 ~ 10월 10일 수출입 현황 [잠정치]"),
        ("twentyday", "2026-10-21", "2026년 10월 1~20일 수출입 현황"),
    ],
)
def test_requested_month_is_selected(kind, day, title):
    from app.release_period import ReleaseTarget

    html = (
        '<a href="./materialView.do?num=1">2025년 10월 수출입 동향</a>'
        f'<a href="./materialView.do?num=2">{title}</a>'
    )
    target = ReleaseTarget(kind, dt.date.fromisoformat(day))
    assert pick_latest_article(html, target, "https://eiec.kdi.re.kr/policy/").endswith("num=2")


def test_previous_month_is_not_treated_as_current_release():
    from app.release_period import ReleaseTarget

    html = '<a href="./materialView.do?num=1">2026년 9월 수출입 동향</a>'
    assert pick_latest_article(html, ReleaseTarget("monthly", dt.date(2026, 11, 1)), "https://eiec.kdi.re.kr/policy/") is None


def test_http_200_error_page_is_not_a_valid_unpublished_listing():
    from app.release_period import ReleaseTarget
    from app.release_source import SourceError

    with pytest.raises(SourceError, match="목록"):
        pick_latest_article("<h2>정상적인 접근이 아닙니다!!!</h2>", ReleaseTarget("monthly", dt.date(2026, 11, 1)), "https://eiec.kdi.re.kr/policy/")


@pytest.mark.parametrize("period", ["2026년 10월 1~10일", "2026년 10월 1~20일", "2026년 10월 20일 수출입 현황"])
def test_monthly_never_accepts_partial_period(period):
    from app.release_period import ReleaseTarget

    assert not ReleaseTarget("monthly", dt.date(2026, 11, 1)).matches_period(period)


@pytest.mark.parametrize("published, valid", [("2026.10.12", True), ("2026.10.11", True), ("2026.10.10", False), ("2026.10.13", False), ("bad", False)])
def test_delayed_publication_date_bounds(published, valid):
    from app.release_period import ReleaseTarget

    assert ReleaseTarget("tenday", dt.date(2026, 10, 12)).matches_publication_date(published) is valid


@pytest.mark.parametrize("kind, day, number", [("tenday", "2026-10-12", "287971"), ("twentyday", "2026-10-21", "288360"), ("monthly", "2026-11-01", None)])
def test_live_eiec_search_fixture_matches_only_requested_release(kind, day, number):
    from app.release_period import ReleaseTarget

    html = (Path(__file__).parent / "fixtures/eiec_search_20261101.html").read_text()
    url = pick_latest_article(html, ReleaseTarget(kind, dt.date.fromisoformat(day)), "https://eiec.kdi.re.kr/policy/")
    if number is None:
        assert url is None
    else:
        assert f"num={number}&" in url
