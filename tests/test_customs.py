"""관세청 클라이언트 — XML 파싱·페이지네이션·캐시·에러 테스트."""

import httpx
import pytest
from fastapi import HTTPException

from app.customs import parse_xml

from .conftest import make_item, make_xml

pytestmark = pytest.mark.unit


class TestParseXml:
    def test_basic(self):
        rows, total = parse_xml(make_xml([make_item(exp=2_0000_0000)]))
        assert total == 1
        assert rows[0]["country"] == "중국"
        assert rows[0]["exp"] == 2_0000_0000

    def test_error_code_raises(self):
        with pytest.raises(HTTPException) as ei:
            parse_xml(make_xml([], code="30"))
        assert ei.value.status_code == 502

    def test_malformed_xml_raises(self):
        with pytest.raises(HTTPException):
            parse_xml("not xml at all <<<")

    def test_total_row_filtered(self):
        # '총계' 요약 행은 합산 중복 방지를 위해 파싱에서 제외
        total_item = (
            "<item><year>총계</year><statCdCntnKor1>-</statCdCntnKor1><statKor>-</statKor>"
            "<hsCd>-</hsCd><expDlr>999</expDlr><impDlr>0</impDlr><balPayments>999</balPayments></item>"
        )
        rows, _ = parse_xml(make_xml([total_item, make_item()]))
        assert len(rows) == 1
        assert rows[0]["country"] == "중국"

    def test_comma_separated_numbers(self):
        item = (
            "<item><year>2026.05</year><statKor>미국</statKor><hsCd>87</hsCd>"
            "<expDlr>1,234,567</expDlr><impDlr>0</impDlr><balPayments>1,234,567</balPayments></item>"
        )
        rows, _ = parse_xml(make_xml([item]))
        assert rows[0]["exp"] == 1234567.0


class TestPagination:
    async def test_collects_all_pages(self, make_client, settings):
        settings.rows_per_page = 2
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            page = int(request.url.params["pageNo"])
            calls.append(page)
            items = {
                1: [make_item(country="중국"), make_item(country="미국")],
                2: [make_item(country="일본")],
            }.get(page, [])
            return httpx.Response(200, text=make_xml(items, total=3))

        client = make_client(handler)
        rows = await client.fetch_rows("202605", "85")
        assert len(rows) == 3
        assert calls == [1, 2]

    async def test_cache_hit_skips_network(self, make_client):
        counter = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            counter["n"] += 1
            return httpx.Response(200, text=make_xml([make_item()]))

        client = make_client(handler)
        await client.fetch_rows("202605", "85")
        await client.fetch_rows("202605", "85")  # 캐시 적중
        assert counter["n"] == 1

    async def test_refresh_bypasses_cache(self, make_client):
        counter = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            counter["n"] += 1
            return httpx.Response(200, text=make_xml([make_item()]))

        client = make_client(handler)
        await client.fetch_rows("202605", "85")
        await client.fetch_rows("202605", "85", refresh=True)
        assert counter["n"] == 2

    async def test_missing_key_raises(self, make_client, settings):
        settings.customs_service_key = ""
        client = make_client(lambda r: httpx.Response(200, text=make_xml([])))
        with pytest.raises(HTTPException) as ei:
            await client.fetch_rows("202605", "85")
        assert ei.value.status_code == 500

    async def test_http_error_raises_502(self, make_client):
        client = make_client(lambda r: httpx.Response(500))
        with pytest.raises(HTTPException) as ei:
            await client.fetch_rows("202605", "85")
        assert ei.value.status_code == 502


class TestRateLimit429:
    """429(호출 제한)는 즉시 실패가 아니라 백오프 재시도 대상이다 (2026-08-17)."""

    async def test_429_then_200_succeeds(self, settings, monkeypatch):
        from app.cache import FileCache
        from app.customs import CustomsClient
        import app.customs as customs_mod

        settings = settings.model_copy(update={"retries": 2, "retry_backoff": 0.0})
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429, headers={"Retry-After": "0"})
            return httpx.Response(200, text=make_xml([make_item()]))

        slept: list[float] = []

        async def fake_sleep(s):
            slept.append(s)

        monkeypatch.setattr(customs_mod.asyncio, "sleep", fake_sleep)
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = CustomsClient(settings, FileCache(settings.cache_dir), http)

        rows = await client.fetch_rows("202605", "85")

        assert len(rows) == 1
        assert calls["n"] == 2
        assert len(slept) == 1

    async def test_429_exhausted_raises_502_with_429_in_message(self, settings):
        from app.cache import FileCache
        from app.customs import CustomsClient

        settings = settings.model_copy(update={"retries": 1, "retry_backoff": 0.0})
        http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(429)))
        client = CustomsClient(settings, FileCache(settings.cache_dir), http)

        with pytest.raises(HTTPException) as ei:
            await client.fetch_rows("202605", "85")
        assert ei.value.status_code == 502
        assert "429" in str(ei.value.detail)
