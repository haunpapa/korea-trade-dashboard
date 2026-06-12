"""한국수출입은행 환율 API — 원/달러 매매기준율(deal_bas_r).

발급: koreaexim.go.kr → .env의 EXIM_API_KEY.
미설정/오류 시 None을 반환하므로 대시보드는 환율 라인만 숨깁니다.
월 대표값: 15일 주변 영업일의 고시 환율.
"""

import asyncio
import logging

from .aggregate import month_seq
from .customs import CustomsClient

logger = logging.getLogger(__name__)

FX_URL = "https://oapi.koreaexim.go.kr/site/program/financial/exchangeJSON"
_TRY_DAYS = ("15", "16", "14", "17", "13", "18", "12")  # 비영업일 대비 15일 주변 탐색


async def fetch_fx_usd(client: CustomsClient, yymm: str, refresh: bool = False) -> float | None:
    """해당 월의 원/달러 매매기준율 1건. 실패/미설정 시 None."""
    if not client.settings.exim_api_key:
        return None
    key = f"fx_{yymm}"
    if not refresh and (cached := client.cache.get(key)) is not None:
        return cached
    for day in _TRY_DAYS:
        try:
            r = await client.client.get(
                FX_URL,
                params={
                    "authkey": client.settings.exim_api_key,
                    "searchdate": f"{yymm}{day}",
                    "data": "AP01",
                },
                timeout=client.settings.request_timeout,
            )
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, list) or not data:
                continue  # 비영업일 → 다음 후보일
            for row in data:
                if row.get("cur_unit") == "USD" and row.get("result") == 1:
                    rate = round(float(str(row.get("deal_bas_r", "0")).replace(",", "")), 1)
                    if rate > 0:
                        client.cache.set(key, rate)
                        return rate
        except Exception as e:  # noqa: BLE001 — 환율은 부가 정보, 실패해도 본 기능 유지
            logger.warning("환율 조회 실패 %s%s: %s", yymm, day, e)
            return None
    return None


async def build_fx_trend(
    client: CustomsClient, end_yymm: str, months: int = 12, refresh: bool = False
) -> list[dict]:
    """월별 원/달러 환율 시계열 [{m, rate}, ...] — 추세 차트 오버레이용."""
    seq = month_seq(end_yymm, months)
    rates = await asyncio.gather(*(fetch_fx_usd(client, ym, refresh) for ym in seq))
    return [{"m": f"{ym[2:4]}.{ym[4:]}", "rate": r} for ym, r in zip(seq, rates, strict=True)]
