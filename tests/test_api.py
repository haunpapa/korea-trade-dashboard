"""FastAPI 엔드포인트 통합 테스트 (MockTransport)."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.aggregate import build_trend, sectors, totals_and_regions
from app.main import app

from .conftest import make_item, make_xml

pytestmark = pytest.mark.integration


def _handler(request: httpx.Request) -> httpx.Response:
    """모든 HS 요청에 고정 응답 — 중국/미국/인도네시아 3행."""
    items = [
        make_item(country="중국", exp=3_0000_0000, imp=1_0000_0000),
        make_item(country="미국", exp=2_0000_0000, imp=1_0000_0000),
        make_item(country="인도네시아", exp=1_0000_0000, imp=5000_0000),
    ]
    return httpx.Response(200, text=make_xml(items))


@pytest.fixture
def mock_customs(make_client):
    return make_client(_handler)


class TestBuilders:
    async def test_totals_and_regions(self, mock_customs):
        result = await totals_and_regions(mock_customs, "202605")
        # chapter 99개 × (3+2+1)억$ = 수출 594 / 수입 247.5
        assert result["totals"]["exports"] == pytest.approx(594.0)
        assert result["totals"]["balance"] == pytest.approx(346.5)
        names = [r["name"] for r in result["regions"]]
        assert names[0] == "중국"
        assert "아세안" in names  # 인도네시아 → 아세안 (인도 아님)
        assert "인도" not in names

    async def test_sectors_dedup(self, mock_customs):
        secs = await sectors(mock_customs, "202605")
        flat = {i["name"]: i["value"] for g in secs for i in g["items"]}
        # mock은 모든 HS코드에 동일 응답(6억$) → 인위적이지만 차감 동작 검증에 충분
        assert flat["반도체"] == pytest.approx(12.0)  # 8541 + 8542
        # 일반기계 = 84(6억) - 중복코드 4개(8471·8415·8418·8450, 각 6억) = -18억
        assert flat["일반기계"] == pytest.approx(-18.0)

    async def test_build_trend_length(self, mock_customs):
        trend = await build_trend(mock_customs, "202605", months=3)
        assert len(trend) == 3
        assert trend[-1]["m"] == "26.05"


class TestEndpoints:
    def test_health(self):
        with TestClient(app) as c:
            r = c.get("/health")
            assert r.status_code == 200
            assert r.json()["ok"] is True

    def test_dashboard_served(self):
        with TestClient(app) as c:
            r = c.get("/")
            assert r.status_code == 200
            assert "text/html" in r.headers["content-type"]

    def test_invalid_yymm_422(self):
        with TestClient(app) as c:
            assert c.get("/api/monthly?yymm=bad").status_code == 422
            assert c.get("/api/monthly?yymm=202613").status_code == 422

    def test_invalid_group_422(self):
        with TestClient(app) as c:
            assert c.get("/api/sector-trend?group=없는그룹").status_code == 422

    def test_invalid_region_422(self):
        with TestClient(app) as c:
            assert c.get("/api/region-trend?region=화성").status_code == 422

    def test_sectors_endpoint_with_mock(self, mock_customs):
        with TestClient(app) as c:
            app.state.customs = mock_customs
            r = c.get("/api/sectors?yymm=202605")
            assert r.status_code == 200
            groups = {g["name"] for g in r.json()}
            assert "IT·반도체" in groups
