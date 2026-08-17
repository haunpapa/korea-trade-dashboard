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
        import app.customs as customs_mod
        from app.cache import FileCache
        from app.customs import CustomsClient

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

    async def test_daily_quota_429_fails_fast_without_retry(self, settings):
        """returnReasonCode 22(일일 요청제한 초과)는 재시도해도 소용없으므로 즉시 502, 메시지에 '일일' 명시."""
        from app.cache import FileCache
        from app.customs import CustomsClient

        body = ("<OpenAPI_ServiceResponse><cmmMsgHeader>"
                "<errMsg>LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR</errMsg>"
                "<returnAuthMsg>일일 서비스 요청제한 횟수 초과 에러</returnAuthMsg>"
                "<returnReasonCode>22</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>")
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(429, text=body)

        settings = settings.model_copy(update={"retries": 3, "retry_backoff": 0.0})
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = CustomsClient(settings, FileCache(settings.cache_dir), http)

        with pytest.raises(HTTPException) as ei:
            await client.fetch_rows("202605", "85")
        assert calls["n"] == 1
        assert "일일" in str(ei.value.detail)


class TestFetchManyFailure:
    async def test_first_failure_propagates_and_no_orphan_tasks(self, settings):
        """한 HS 가 실패하면 그 예외가 그대로 올라오고, 형제 태스크는 남지 않는다(셧다운 traceback 방지)."""
        import asyncio

        from app.cache import FileCache
        from app.customs import CustomsClient

        def handler(request: httpx.Request) -> httpx.Response:
            if "hsSgn=85" in str(request.url):
                return httpx.Response(500)
            return httpx.Response(200, text=make_xml([make_item()]))

        settings = settings.model_copy(update={"retries": 0})
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = CustomsClient(settings, FileCache(settings.cache_dir), http)

        with pytest.raises(HTTPException) as ei:
            await client.fetch_many("202605", ["84", "85", "86", "87"])
        assert ei.value.status_code == 502

        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
        assert pending == []
