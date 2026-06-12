"""수출입은행 환율 모듈 테스트."""

import json

import httpx
import pytest

from app.fx import build_fx_trend, fetch_fx_usd

pytestmark = pytest.mark.unit

_FX_ROW = {"result": 1, "cur_unit": "USD", "deal_bas_r": "1,391.20", "cur_nm": "미국 달러"}


def _fx_handler(request: httpx.Request) -> httpx.Response:
    if "koreaexim" in str(request.url):
        return httpx.Response(200, text=json.dumps([_FX_ROW]))
    return httpx.Response(404)


async def test_fetch_fx_usd(make_client):
    client = make_client(_fx_handler)
    assert await fetch_fx_usd(client, "202605") == 1391.2


async def test_fx_cache_hit(make_client):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, text=json.dumps([_FX_ROW]))

    client = make_client(handler)
    await fetch_fx_usd(client, "202605")
    await fetch_fx_usd(client, "202605")
    assert calls["n"] == 1


async def test_fx_missing_key_returns_none(make_client, settings):
    settings.exim_api_key = ""
    client = make_client(_fx_handler)
    assert await fetch_fx_usd(client, "202605") is None


async def test_fx_holiday_fallback(make_client):
    """15일이 비영업일(빈 배열)이면 다음 후보일로 재시도."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        d = request.url.params["searchdate"]
        seen.append(d)
        if d.endswith("15"):
            return httpx.Response(200, text="[]")
        return httpx.Response(200, text=json.dumps([_FX_ROW]))

    client = make_client(handler)
    assert await fetch_fx_usd(client, "202605") == 1391.2
    assert seen == ["20260515", "20260516"]


async def test_build_fx_trend(make_client):
    client = make_client(_fx_handler)
    trend = await build_fx_trend(client, "202605", months=3)
    assert [t["m"] for t in trend] == ["26.03", "26.04", "26.05"]
    assert all(t["rate"] == 1391.2 for t in trend)
