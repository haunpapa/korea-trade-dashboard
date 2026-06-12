"""FastAPI 앱 — 관세청 → 수출입동향 섹터 대시보드 API.

실행: uvicorn app.main:app --reload
대시보드: http://localhost:8000/ (같은 출처에서 서빙 → 자동 연동)
"""

import datetime as dt
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import __version__, aggregate
from .cache import FileCache
from .config import get_settings
from .customs import CustomsClient
from .mappings import REGION_NAMES, SECTOR_GROUPS

DASHBOARD_HTML = Path(__file__).resolve().parent.parent / "korea-trade-sector-dashboard.html"


def _default_yymm() -> str:
    """직전 달(확정치 기준). 매월 15일 이후 전월 데이터 안정."""
    today = dt.date.today().replace(day=1) - dt.timedelta(days=1)
    return today.strftime("%Y%m")


def _validate_yymm(yymm: str) -> str:
    if len(yymm) != 6 or not yymm.isdigit() or not 1 <= int(yymm[4:]) <= 12:
        raise HTTPException(422, f"yymm 형식 오류(YYYYMM 필요): {yymm}")
    return yymm


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    async with httpx.AsyncClient() as http:
        app.state.customs = CustomsClient(settings, FileCache(settings.cache_dir), http)
        yield


app = FastAPI(title="관세청 → 수출입동향 섹터 대시보드 API", version=__version__, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _client(request: Request) -> CustomsClient:
    return request.app.state.customs


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    """대시보드 HTML — 같은 출처라 API_BASE 설정 없이 자동 연동됩니다."""
    if not DASHBOARD_HTML.exists():
        raise HTTPException(404, "korea-trade-sector-dashboard.html 파일이 없습니다.")
    return FileResponse(DASHBOARD_HTML, media_type="text/html")


@app.get("/health")
def health(request: Request) -> dict:
    settings = get_settings()
    return {
        "ok": True,
        "version": __version__,
        "service_key_set": bool(settings.customs_service_key),
        "default_yymm": _default_yymm(),
        "cache": _client(request).cache.stats(),
    }


@app.get("/api/monthly")
async def api_monthly(
    request: Request,
    yymm: str | None = Query(default=None, description="조회 년월 YYYYMM"),
    refresh: int = 0,
) -> dict:
    return await aggregate.build_monthly(
        _client(request), _validate_yymm(yymm or _default_yymm()), refresh=bool(refresh)
    )


@app.get("/api/trend")
async def api_trend(
    request: Request,
    months: int = Query(default=12, ge=1, le=36),
    end: str | None = None,
    refresh: int = 0,
) -> list[dict]:
    return await aggregate.build_trend(
        _client(request), _validate_yymm(end or _default_yymm()), months, refresh=bool(refresh)
    )


@app.get("/api/sectors")
async def api_sectors(request: Request, yymm: str | None = None, refresh: int = 0) -> list[dict]:
    return await aggregate.sectors(
        _client(request), _validate_yymm(yymm or _default_yymm()), refresh=bool(refresh)
    )


@app.get("/api/sector-trend")
async def api_sector_trend(
    request: Request,
    group: str,
    months: int = Query(default=12, ge=1, le=36),
    end: str | None = None,
    refresh: int = 0,
) -> list[dict]:
    """산업분야(그룹)별 월별 수출 시계열."""
    if group not in SECTOR_GROUPS:
        raise HTTPException(422, f"group은 {' | '.join(SECTOR_GROUPS)} 중 하나여야 합니다.")
    return await aggregate.build_sector_trend(
        _client(request),
        group,
        _validate_yymm(end or _default_yymm()),
        months,
        refresh=bool(refresh),
    )


@app.get("/api/region-trend")
async def api_region_trend(
    request: Request,
    region: str,
    months: int = Query(default=12, ge=1, le=36),
    end: str | None = None,
    refresh: int = 0,
) -> list[dict]:
    """권역별 월별 수출 시계열 (9대 권역)."""
    if region not in REGION_NAMES:
        raise HTTPException(422, f"region은 {' | '.join(REGION_NAMES)} 중 하나여야 합니다.")
    return await aggregate.build_region_trend(
        _client(request),
        region,
        _validate_yymm(end or _default_yymm()),
        months,
        refresh=bool(refresh),
    )


@app.get("/debug/raw")
async def debug_raw(request: Request, yymm: str | None = None, hs: str = "85") -> dict:
    """실제 응답 필드/세분도 확인용 — customs.py의 F_* 상수 점검."""
    rows = await _client(request).fetch_rows(
        _validate_yymm(yymm or _default_yymm()), hs, refresh=True
    )
    return {"count": len(rows), "sample": rows[:5]}
