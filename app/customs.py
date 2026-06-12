"""관세청 Open API 클라이언트 — 재시도·페이지네이션·XML 파싱.

데이터원: 공공데이터포털 '관세청_품목별 국가별 수출입실적' (getNitemtradeList)
HS코드 기준 월간 확정 통계 (매월 15일경 전월 데이터 현행화).
"""

import asyncio
import logging
import xml.etree.ElementTree as ET
from typing import Any

import httpx
from fastapi import HTTPException

from .cache import FileCache
from .config import Settings

logger = logging.getLogger(__name__)

# 응답 필드명 — data.go.kr '활용신청 명세서'와 다르면 여기만 고치면 됩니다.
# (/debug/raw 로 실제 응답을 확인하세요)
F_PERIOD = "year"
F_COUNTRY = "statCdCntnKor1"  # 국가명 (※ statKor는 '품목명'이므로 주의 — 공식 명세 확인됨)
F_HS = "hsCd"
F_EXP = "expDlr"
F_IMP = "impDlr"
F_BAL = "balPayments"

_OK_CODES = (None, "00", "0")
_RETRYABLE = (httpx.TimeoutException, httpx.TransportError)

Row = dict[str, Any]


def _to_float(x: Any) -> float:
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def parse_xml(text: str) -> tuple[list[Row], int | None]:
    """getNitemtradeList XML → (행 목록, totalCount). 에러 헤더면 HTTPException."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise HTTPException(502, f"관세청 API 응답 파싱 실패: {e}") from e

    rc = root.findtext(".//resultCode") or root.findtext(".//returnReasonCode")
    if rc not in _OK_CODES:
        msg = root.findtext(".//resultMsg") or root.findtext(".//returnAuthMsg") or "API error"
        raise HTTPException(502, f"관세청 API 오류({rc}): {msg}")

    total_text = root.findtext(".//totalCount")
    total = int(total_text) if total_text and total_text.isdigit() else None

    rows: list[Row] = []
    for it in root.iter("item"):
        # '총계' 요약 행은 개별 행의 합과 동일 → 포함 시 2배 중복되므로 제외
        if (it.findtext(F_PERIOD) or "").strip() == "총계":
            continue
        rows.append(
            {
                "period": (it.findtext(F_PERIOD) or "").strip(),
                "country": (it.findtext(F_COUNTRY) or "").strip(),
                "hs": (it.findtext(F_HS) or "").strip(),
                "exp": _to_float(it.findtext(F_EXP)),
                "imp": _to_float(it.findtext(F_IMP)),
                "bal": _to_float(it.findtext(F_BAL)),
            }
        )
    return rows, total


class CustomsClient:
    """관세청 API 비동기 클라이언트. 영구 캐시 + 동시성 제한 + 재시도 + 페이지네이션."""

    def __init__(self, settings: Settings, cache: FileCache, client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.cache = cache
        self.client = client
        self._sem = asyncio.Semaphore(settings.concurrency)

    async def _get(self, params: dict[str, Any]) -> str:
        """재시도(지수 백오프) 포함 단일 GET."""
        last_exc: Exception | None = None
        for attempt in range(self.settings.retries + 1):
            try:
                r = await self.client.get(
                    self.settings.base_url, params=params, timeout=self.settings.request_timeout
                )
                r.raise_for_status()
                return r.text
            except _RETRYABLE as e:
                last_exc = e
                wait = self.settings.retry_backoff * (2**attempt)
                logger.warning(
                    "일시 오류, %.1fs 후 재시도(%d/%d): %s",
                    wait,
                    attempt + 1,
                    self.settings.retries,
                    e,
                )
                await asyncio.sleep(wait)
            except httpx.HTTPStatusError as e:
                raise HTTPException(502, f"관세청 API HTTP {e.response.status_code}") from e
        raise HTTPException(504, f"관세청 API 연결 실패(재시도 소진): {last_exc}")

    async def _fetch_pages(self, yymm: str, hs: str) -> list[Row]:
        """totalCount 기반 페이지네이션 — 행 누락 없이 전체 수집."""
        if not self.settings.customs_service_key:
            raise HTTPException(500, "CUSTOMS_SERVICE_KEY 환경변수가 비어 있습니다 (.env 확인).")

        rows: list[Row] = []
        page = 1
        while page <= self.settings.max_pages:
            params = {
                "serviceKey": self.settings.customs_service_key,
                "strtYymm": yymm,
                "endYymm": yymm,
                "hsSgn": hs,
                "numOfRows": self.settings.rows_per_page,
                "pageNo": page,
            }
            text = await self._get(params)
            page_rows, total = parse_xml(text)
            rows.extend(page_rows)
            if total is None or len(rows) >= total or not page_rows:
                break
            page += 1
        else:
            logger.warning("페이지 상한(%d) 도달: yymm=%s hs=%s", self.settings.max_pages, yymm, hs)
        return rows

    async def fetch_rows(self, yymm: str, hs: str, refresh: bool = False) -> list[Row]:
        key = f"rows_{yymm}_{hs or 'ALL'}"
        if not refresh and (cached := self.cache.get(key)) is not None:
            return cached
        async with self._sem:
            rows = await self._fetch_pages(yymm, hs)
        self.cache.set(key, rows)
        return rows

    async def fetch_many(
        self, yymm: str, hs_list: list[str] | tuple[str, ...], refresh: bool = False
    ) -> dict[str, list[Row]]:
        """여러 HS부호 동시 조회 (세마포어로 동시성 제한)."""
        results = await asyncio.gather(*(self.fetch_rows(yymm, hs, refresh) for hs in hs_list))
        return dict(zip(hs_list, results, strict=True))
