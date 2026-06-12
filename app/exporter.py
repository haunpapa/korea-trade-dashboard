"""일일 자동 export — 서버(Railway)가 관세청 데이터를 수집해 GitHub data/에 직접 push.

PC의 scripts/export_static.py와 같은 일을 서버 안에서 스케줄로 수행합니다.

설정 (환경변수 또는 .env):
  AUTO_EXPORT_KST="07:30"  매일 이 시각(한국시간)에 자동 실행. 비우면 비활성.
  GITHUB_TOKEN=...         Contents: Read/Write — 없으면 수집·캐시 워밍업만 하고 push 생략.
  EXPORT_KEY=...           /admin/export 수동 트리거 키. 비우면 엔드포인트 비활성.

동작:
  1) 최근 2개월 캐시 삭제 → 확정치 현행화(매월 15일경)가 반영되도록 강제 재조회
  2) collect()로 대시보드 데이터 전체 수집 (이전 달들은 영구 캐시 재사용 → API 호출 최소)
  3) GitHub Contents API로 data/*.json 커밋 (git 불필요)
"""

import asyncio
import base64
import datetime as dt
import json
import logging
from typing import Any

import httpx

from . import aggregate, fx
from .config import Settings, get_settings
from .customs import CustomsClient
from .mappings import REGION_NAMES, SECTOR_GROUPS

logger = logging.getLogger(__name__)

KST = dt.timezone(dt.timedelta(hours=9), "KST")

#: /health에 노출되는 마지막 실행 상태
status: dict[str, Any] = {
    "enabled": False,
    "running": False,
    "next_run": None,
    "last_start": None,
    "last_ok": None,
    "last_error": None,
}


def default_yymm() -> str:
    """직전 달(KST 기준) — 확정 통계 대상."""
    today = dt.datetime.now(KST).date().replace(day=1) - dt.timedelta(days=1)
    return today.strftime("%Y%m")


async def collect(client: CustomsClient, end_yymm: str, months: int) -> dict[str, Any]:
    """모든 대시보드 데이터를 수집해 파일명→내용 dict로 반환.

    scripts/export_static.py와 공유되는 단일 구현입니다.
    """
    logger.info("수집 시작: end=%s months=%d", end_yymm, months)
    monthly = await aggregate.build_monthly(client, end_yymm)
    trend = await aggregate.build_trend(client, end_yymm, months)
    sector_trend = {
        g: await aggregate.build_sector_trend(client, g, end_yymm, months) for g in SECTOR_GROUPS
    }
    region_trend = {
        r: await aggregate.build_region_trend(client, r, end_yymm, months) for r in REGION_NAMES
    }
    item_trend = await aggregate.build_item_trends(client, end_yymm, months)
    item_countries = await aggregate.build_item_countries(client, end_yymm)
    fx_trend = await fx.build_fx_trend(client, end_yymm, months)
    meta = {
        "generated_at": dt.datetime.now(KST).isoformat(timespec="seconds"),
        "end_yymm": end_yymm,
        "months": months,
        "source": "관세청 무역통계 API (HS 기준)",
    }
    return {
        "monthly.json": monthly,
        "trend.json": trend,
        "sector-trend.json": sector_trend,
        "region-trend.json": region_trend,
        "item-trend.json": item_trend,
        "item-countries.json": item_countries,
        "fx.json": fx_trend,
        "meta.json": meta,
    }


def purge_recent_cache(client: CustomsClient, yymms: list[str]) -> int:
    """해당 년월이 포함된 캐시 파일 삭제 — 최신 월 현행화 반영용."""
    n = 0
    for p in client.cache.cache_dir.glob("*.json"):
        if any(ym in p.name for ym in yymms):
            try:
                p.unlink()
                n += 1
            except OSError:  # pragma: no cover
                pass
    return n


async def push_to_github(data: dict[str, Any], settings: Settings) -> None:
    """GitHub Contents API로 data/*.json 업로드."""
    headers = {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
    }
    async with httpx.AsyncClient(headers=headers, timeout=30) as http:
        for name, content in data.items():
            url = (
                f"https://api.github.com/repos/{settings.github_repo}/contents/data/{name}"
            )
            sha = None
            r = await http.get(url, params={"ref": settings.github_branch})
            if r.status_code == 200:
                sha = r.json().get("sha")
            body = {
                "message": f"data: {name} 갱신 (서버 자동 수집)",
                "content": base64.b64encode(
                    json.dumps(content, ensure_ascii=False, indent=1).encode("utf-8")
                ).decode(),
                "branch": settings.github_branch,
                **({"sha": sha} if sha else {}),
            }
            r = await http.put(url, json=body)
            if r.status_code not in (200, 201):
                raise RuntimeError(f"업로드 실패 {name}: HTTP {r.status_code} {r.text[:200]}")
            logger.info("업로드 완료: data/%s", name)


async def run_export(
    client: CustomsClient, settings: Settings, months: int = 12, push: bool = True
) -> dict[str, Any]:
    """수집 → (옵션) GitHub push. 동시 실행 방지 가드 포함."""
    if status["running"]:
        raise RuntimeError("export가 이미 실행 중입니다.")
    status["running"] = True
    status["last_start"] = dt.datetime.now(KST).isoformat(timespec="seconds")
    try:
        end = default_yymm()
        recent = aggregate.month_seq(end, 2)
        purged = purge_recent_cache(client, recent)
        logger.info("최근 %s 캐시 %d건 삭제(현행화 반영)", recent, purged)

        data = await collect(client, end, months)

        pushed = False
        if push and settings.github_token:
            await push_to_github(data, settings)
            pushed = True
        elif push:
            logger.warning("GITHUB_TOKEN 미설정 — push 생략(캐시 워밍업만 수행)")

        status["last_ok"] = dt.datetime.now(KST).isoformat(timespec="seconds")
        status["last_error"] = None
        return {"end_yymm": end, "months": months, "pushed": pushed, "purged_cache": purged}
    except Exception as e:
        status["last_error"] = f"{type(e).__name__}: {e}"
        raise
    finally:
        status["running"] = False


async def run_export_logged(client: CustomsClient, settings: Settings, months: int = 12) -> None:
    """백그라운드 태스크용 래퍼 — 예외를 로그로만 남김."""
    try:
        result = await run_export(client, settings, months)
        logger.info("자동 export 완료: %s", result)
    except Exception:
        logger.exception("자동 export 실패 — 다음 주기에 재시도")


def _next_run(now: dt.datetime, hh: int, mm: int) -> dt.datetime:
    nxt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if nxt <= now:
        nxt += dt.timedelta(days=1)
    return nxt


async def scheduler(client: CustomsClient) -> None:
    """매일 AUTO_EXPORT_KST 시각(KST)에 run_export 실행하는 무한 루프."""
    settings = get_settings()
    spec = settings.auto_export_kst.strip()
    if not spec:
        logger.info("AUTO_EXPORT_KST 미설정 — 자동 export 비활성")
        return
    try:
        hh, mm = (int(x) for x in spec.split(":"))
        assert 0 <= hh <= 23 and 0 <= mm <= 59
    except (ValueError, AssertionError):
        logger.error("AUTO_EXPORT_KST 형식 오류(HH:MM 필요): %r — 자동 export 비활성", spec)
        return

    status["enabled"] = True
    logger.info("자동 export 활성 — 매일 %02d:%02d KST", hh, mm)
    while True:
        now = dt.datetime.now(KST)
        nxt = _next_run(now, hh, mm)
        status["next_run"] = nxt.isoformat(timespec="seconds")
        await asyncio.sleep((nxt - now).total_seconds())
        await run_export_logged(client, settings, settings.auto_export_months)
        await asyncio.sleep(61)  # 같은 분 내 중복 실행 방지
