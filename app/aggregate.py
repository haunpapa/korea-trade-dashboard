"""집계 로직 — 관세청 행 데이터 → 대시보드 JSON 스키마.

순수 함수(테스트 용이)와 CustomsClient를 쓰는 빌더로 구성.
금액 단위: 억 달러(USD 1e8).
"""

import asyncio
import datetime as dt
import logging
from collections import defaultdict
from typing import Any

from .customs import CustomsClient, Row
from .mappings import ALL_CHAPTERS, REGION_MAP, SECTOR_BUCKETS

logger = logging.getLogger(__name__)

USD_TO_EOK = 1e8  # 1억 달러


# ---------------------------------------------------------------------
# 순수 함수
# ---------------------------------------------------------------------
def sum_eok(rows: list[Row], field: str) -> float:
    return sum(r[field] for r in rows) / USD_TO_EOK


def yoy(cur: float | None, prev: float | None) -> float | None:
    if not prev or cur is None:
        return None
    return round((cur - prev) / prev * 100, 1)


def prev_year(yymm: str) -> str:
    return f"{int(yymm[:4]) - 1}{yymm[4:]}"


def month_seq(end_yymm: str, months: int) -> list[str]:
    seq, y, m = [], int(end_yymm[:4]), int(end_yymm[4:])
    for _ in range(months):
        seq.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    seq.reverse()
    return seq


def region_of(country: str) -> str | None:
    """국가명 → 권역. 완전일치 우선, 그 외 가장 긴 부분일치.

    (예: '인도네시아'는 아세안의 완전일치가 '인도'(부분일치)보다 우선 → 아세안)
    """
    best: tuple[int, int, str] | None = None  # (exact, len(member), region)
    for region in REGION_MAP:
        for m in region.members:
            if m == country:
                cand = (1, len(m), region.name)
            elif m in country:
                cand = (0, len(m), region.name)
            else:
                continue
            if best is None or cand[:2] > best[:2]:
                best = cand
    return best[2] if best else None


def deduct_overlaps(code_val: dict[str, float]) -> dict[str, float]:
    """품목별 수출액 산출 + HS 중복 자동 차감.

    어떤 품목 A의 코드 ca(예: '84')가 다른 품목 B의 코드 cb(예: '8471')의
    접두사이면 cb 금액이 A에 이중 포함 → A에서 차감.
    """
    all_codes = {c for b in SECTOR_BUCKETS.values() for c in b.hs}
    values: dict[str, float] = {}
    for item, bucket in SECTOR_BUCKETS.items():
        total = sum(code_val.get(c, 0.0) for c in bucket.hs)
        # 다른 품목의 더 세분화된 코드가 내 코드 하위에 있으면 차감
        for ca in bucket.hs:
            nested = {
                cb for cb in all_codes if cb != ca and cb.startswith(ca) and cb not in bucket.hs
            }
            total -= sum(code_val.get(cb, 0.0) for cb in nested)
        values[item] = round(total, 1)
    return values


# ---------------------------------------------------------------------
# 빌더 (CustomsClient 사용)
# ---------------------------------------------------------------------
async def totals_and_regions(client: CustomsClient, yymm: str, refresh: bool = False) -> dict:
    """전 chapter(01~99) 합산 → 정확한 총수출/수입/수지 + 권역별 수출."""
    key = f"total_v2_{yymm}"
    if not refresh and (cached := client.cache.get(key)) is not None:
        return cached

    chapters = await client.fetch_many(yymm, ALL_CHAPTERS, refresh)
    all_rows = [r for rows in chapters.values() for r in rows]
    exports = sum_eok(all_rows, "exp")
    imports = sum_eok(all_rows, "imp")
    totals = {
        "exports": round(exports, 1),
        "imports": round(imports, 1),
        "balance": round(exports - imports, 1),
    }

    by_region: dict[str, float] = defaultdict(float)
    for r in all_rows:
        if region := region_of(r["country"]):
            by_region[region] += r["exp"]
    regions = [
        {"name": name, "value": round(v / USD_TO_EOK, 1)} for name, v in by_region.items() if v > 0
    ]
    regions.sort(key=lambda x: -x["value"])

    result = {"totals": totals, "regions": regions}
    client.cache.set(key, result)
    return result


async def sectors(client: CustomsClient, yymm: str, refresh: bool = False) -> list[dict]:
    """SECTOR_BUCKETS 기준 품목별 수출액 (HS 중복 자동 차감)."""
    needed = sorted({c for b in SECTOR_BUCKETS.values() for c in b.hs})
    fetched = await client.fetch_many(yymm, needed, refresh)
    code_val = {c: sum_eok(rows, "exp") for c, rows in fetched.items()}
    values = deduct_overlaps(code_val)

    grouped: dict[str, list[dict]] = defaultdict(list)
    for item, bucket in SECTOR_BUCKETS.items():
        grouped[bucket.group].append({"name": item, "value": values[item], "_star": bucket.star})
    return [{"name": g, "items": items} for g, items in grouped.items()]


async def build_monthly(client: CustomsClient, yymm: str, refresh: bool = False) -> dict:
    tr, sec, tr_prev, sec_prev = await asyncio.gather(
        totals_and_regions(client, yymm, refresh),
        sectors(client, yymm, refresh),
        totals_and_regions(client, prev_year(yymm), refresh),
        sectors(client, prev_year(yymm), refresh),
    )

    t, tp = tr["totals"], tr_prev["totals"]
    totals = {
        "exports": t["exports"],
        "exportsYoY": yoy(t["exports"], tp["exports"]),
        "imports": t["imports"],
        "importsYoY": yoy(t["imports"], tp["imports"]),
        "balance": t["balance"],
        "dailyAvg": None,  # 조업일수 미제공 → null (HTML이 graceful 처리)
        "dailyAvgYoY": None,
    }

    prev_val = {i["name"]: i["value"] for g in sec_prev for i in g["items"]}
    groups = []
    for g in sec:
        items = [
            {
                "name": i["name"],
                "value": i["value"],
                "yoy": yoy(i["value"], prev_val.get(i["name"])),
                **({"star": True} if i.get("_star") else {}),
            }
            for i in g["items"]
        ]
        groups.append({"name": g["name"], "items": items})

    prev_reg = {r["name"]: r["value"] for r in tr_prev["regions"]}
    regions = [
        {"name": r["name"], "value": r["value"], "yoy": yoy(r["value"], prev_reg.get(r["name"]))}
        for r in tr["regions"][:7]
    ]

    y, m = yymm[:4], int(yymm[4:])
    return {
        "tab": "월간 동향",
        "tabDay": "1일 발표 · 산업부",
        "granularity": "full",
        "period": f"{y}년 {m}월",
        "status": "월간(관세청 HS 기준)",
        "src": "관세청 무역통계 API",
        "date": dt.date.today().isoformat(),
        "totals": totals,
        "groups": groups,
        "regions": regions,
    }


async def build_trend(
    client: CustomsClient, end_yymm: str, months: int = 12, refresh: bool = False
) -> list[dict]:
    seq = month_seq(end_yymm, months)
    results = await asyncio.gather(*(totals_and_regions(client, ym, refresh) for ym in seq))
    return [
        {"m": f"{ym[2:4]}.{ym[4:]}", "exp": r["totals"]["exports"], "bal": r["totals"]["balance"]}
        for ym, r in zip(seq, results, strict=True)
    ]


async def build_sector_trend(
    client: CustomsClient, group: str, end_yymm: str, months: int = 12, refresh: bool = False
) -> list[dict]:
    """산업분야(그룹)별 월별 수출 시계열."""
    seq = month_seq(end_yymm, months)
    results = await asyncio.gather(*(sectors(client, ym, refresh) for ym in seq))
    out: list[dict[str, Any]] = []
    for ym, secs in zip(seq, results, strict=True):
        g = next((x for x in secs if x["name"] == group), None)
        val = round(sum(i["value"] for i in g["items"]), 1) if g else None
        out.append({"m": f"{ym[2:4]}.{ym[4:]}", "exp": val})
    return out


async def build_item_trends(
    client: CustomsClient, end_yymm: str, months: int = 12, refresh: bool = False
) -> dict[str, list[dict]]:
    """전 품목의 월별 수출 시계열 {품목명: [{m, exp}, ...]} — 모달 차트용."""
    seq = month_seq(end_yymm, months)
    results = await asyncio.gather(*(sectors(client, ym, refresh) for ym in seq))
    out: dict[str, list[dict]] = {item: [] for item in SECTOR_BUCKETS}
    for ym, secs in zip(seq, results, strict=True):
        label = f"{ym[2:4]}.{ym[4:]}"
        vals = {i["name"]: i["value"] for g in secs for i in g["items"]}
        for item in SECTOR_BUCKETS:
            out[item].append({"m": label, "exp": vals.get(item)})
    return out


async def build_region_trend(
    client: CustomsClient, region: str, end_yymm: str, months: int = 12, refresh: bool = False
) -> list[dict]:
    """권역별 월별 수출 시계열 — 대시보드 권역 추이 탭용."""
    seq = month_seq(end_yymm, months)
    results = await asyncio.gather(*(totals_and_regions(client, ym, refresh) for ym in seq))
    out: list[dict[str, Any]] = []
    for ym, r in zip(seq, results, strict=True):
        match = next((x for x in r["regions"] if x["name"] == region), None)
        out.append({"m": f"{ym[2:4]}.{ym[4:]}", "exp": match["value"] if match else None})
    return out
