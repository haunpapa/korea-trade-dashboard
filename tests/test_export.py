"""정적 내보내기 스크립트(scripts/export_static.py) 테스트."""

import json

import httpx
import pytest

from scripts.export_static import collect, write_outputs

from .conftest import make_item, make_xml

pytestmark = pytest.mark.unit


def _handler(request: httpx.Request) -> httpx.Response:
    items = [
        make_item(country="중국", exp=3_0000_0000, imp=1_0000_0000),
        make_item(country="미국", exp=2_0000_0000, imp=1_0000_0000),
    ]
    return httpx.Response(200, text=make_xml(items))


async def test_collect_and_write(make_client, tmp_path):
    client = make_client(_handler)
    data = await collect(client, "202605", months=3)

    assert set(data) == {
        "monthly.json", "trend.json", "sector-trend.json", "region-trend.json",
        "item-trend.json", "meta.json",
    }
    assert len(data["item-trend.json"]["반도체"]) == 3
    assert data["monthly.json"]["totals"]["exports"] == pytest.approx(495.0)  # 99 ch × 5억$
    assert len(data["trend.json"]) == 3
    assert "IT·반도체" in data["sector-trend.json"]
    assert "중국" in data["region-trend.json"]
    assert data["meta.json"]["end_yymm"] == "202605"

    outdir = tmp_path / "data"
    paths = write_outputs(data, outdir)
    assert len(paths) == 6
    loaded = json.loads((outdir / "monthly.json").read_text(encoding="utf-8"))
    assert loaded["totals"]["exports"] == pytest.approx(495.0)
