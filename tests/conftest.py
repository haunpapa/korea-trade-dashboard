"""공용 픽스처 — MockTransport 기반 관세청 API 클라이언트."""

from collections.abc import Callable

import httpx
import pytest

from app.cache import FileCache
from app.config import Settings
from app.customs import CustomsClient


def make_item(
    country: str = "중국",
    hs: str = "85",
    exp: float = 1_0000_0000,
    imp: float = 5000_0000,
    period: str = "2026.05",
) -> str:
    return (
        f"<item><year>{period}</year><statCdCntnKor1>{country}</statCdCntnKor1>"
        f"<statKor>품목명예시</statKor><hsCd>{hs}</hsCd>"
        f"<expDlr>{exp:.0f}</expDlr><impDlr>{imp:.0f}</impDlr>"
        f"<balPayments>{exp - imp:.0f}</balPayments></item>"
    )


def make_xml(items: list[str], total: int | None = None, code: str = "00") -> str:
    total_tag = f"<totalCount>{total if total is not None else len(items)}</totalCount>"
    return (
        "<response>"
        f"<header><resultCode>{code}</resultCode><resultMsg>OK</resultMsg></header>"
        f"<body><items>{''.join(items)}</items>{total_tag}</body>"
        "</response>"
    )


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        customs_service_key="TESTKEY",
        exim_api_key="TESTEXIM",
        cache_dir=tmp_path / "cache",
        retries=0,
        concurrency=4,
    )


@pytest.fixture
def make_client(settings) -> Callable[[Callable], CustomsClient]:
    def _make(handler: Callable[[httpx.Request], httpx.Response]) -> CustomsClient:
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return CustomsClient(settings, FileCache(settings.cache_dir), http)

    return _make
