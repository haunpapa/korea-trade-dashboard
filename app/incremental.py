"""증분 수집 — 이미 발행된 data/*.json 의 달은 재사용하고 빠진 달만 새로 수집해 이어 붙인다.

배경(2026-08-17): 캐시가 빈 환경(새 PC·Railway)에서 12개월 전체를 콜드 수집하면 ~1,500회 호출로
data.go.kr 일일 쿼터를 넘긴다. 추이 시계열은 모두 ``[{"m": "YY.MM", ...}]`` 형태라 달 단위로
잘라 붙일 수 있으므로, 이전 산출물에 있는 달은 그대로 쓰고 없는 달만 ``months=1`` 로 만든다.

이 모듈은 순수 함수만 둔다(네트워크 없음). 조립은 app.exporter.collect 가 한다.
"""

from __future__ import annotations

from typing import Any

Point = dict[str, Any]
Series = list[Point]


def label(yymm: str) -> str:
    """'202607' → '26.07' (시계열 포인트의 m 라벨)."""
    return f"{yymm[2:4]}.{yymm[4:]}"


def missing_months(prior: Series | None, seq: list[str]) -> list[str]:
    """seq 중 prior 시계열에 라벨이 없는 달(YYYYMM) 목록 — 순서 유지."""
    have = {p.get("m") for p in (prior or [])}
    return [ym for ym in seq if label(ym) not in have]


def stitch_series(prior: Series | None, fresh: dict[str, Point], seq: list[str]) -> Series:
    """창(seq) 순서대로 시계열을 조립한다. fresh(YYYYMM→포인트) 우선, 없으면 prior, 둘 다 없으면 null 포인트.

    입력은 변경하지 않고 새 리스트를 돌려준다.
    """
    by_label = {p["m"]: p for p in (prior or []) if "m" in p}
    out: Series = []
    for ym in seq:
        lb = label(ym)
        if ym in fresh:
            out.append(dict(fresh[ym]))
        elif lb in by_label:
            out.append(dict(by_label[lb]))
        else:
            out.append({"m": lb, "exp": None})
    return out


def stitch_series_map(
    prior: dict[str, Series] | None,
    fresh: dict[str, dict[str, Series]],
    seq: list[str],
    *,
    keys: list[str] | tuple[str, ...],
) -> dict[str, Series]:
    """{키: 시계열} 묶음(sector/region/item)을 키별로 stitch_series 한다.

    fresh 는 {YYYYMM: {키: [1개 포인트]}} — 각 달을 months=1 로 빌드한 결과.
    """
    prior = prior or {}
    out: dict[str, Series] = {}
    for k in keys:
        fresh_k = {ym: block[k][0] for ym, block in fresh.items() if k in block and block[k]}
        out[k] = stitch_series(prior.get(k), fresh_k, seq)
    return out
