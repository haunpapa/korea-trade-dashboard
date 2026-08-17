"""release_store.py — 파싱된 블록을 data/release.json에 병합하는 라이브러리.

Public API
----------
- merge_release_block(path, kind, block, *, source_url) -> dict
- block_changed(path, kind, block) -> bool
"""

from __future__ import annotations

import datetime
import json
from datetime import timezone, timedelta
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------

def _now_kst() -> str:
    """현재 KST 시각을 ISO 8601 초 단위 문자열로 반환한다."""
    kst = timezone(timedelta(hours=9))
    return datetime.datetime.now(kst).isoformat(timespec="seconds")


def _load_existing(path: Path) -> dict:
    """파일이 존재하면 JSON을 로드하고, 없으면 빈 dict를 반환한다."""
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def merge_release_block(
    path,
    kind: str,
    block: dict,
    *,
    source_url: str | None = None,
) -> dict:
    """파싱된 블록을 JSON 파일에 병합하고 결과 dict를 반환한다.

    Args:
        path:       저장할 파일 경로 (Path 또는 str).
        kind:       블록 종류 ("monthly" | "tenday" | "twentyday").
        block:      병합할 블록 값 (kind로 감싸지 않은 내부 dict).
        source_url: 출처 URL (선택). 제공 시 "source_url" 키에 저장.

    Returns:
        병합된 전체 dict. 호출자의 block을 변경하지 않는다.

    Notes:
        - 파일이 없으면 새로 생성한다.
        - 기존 파일이 있으면 해당 kind만 덮어쓰고 나머지 kind는 보존한다.
        - generated_at은 항상 현재 KST 시각으로 갱신한다.
        - 파일은 UTF-8 JSON (ensure_ascii=False, indent=1) + 후행 개행으로 저장한다.
    """
    path = Path(path)

    # 기존 데이터 로드 — 불변성: 반환된 dict를 그대로 수정하지 않고 새 dict 구성
    existing = _load_existing(path)

    # 새 dict 구성 (기존 kind들 보존 + 이번 kind 업데이트)
    merged: dict[str, Any] = {**existing, kind: block}
    merged["generated_at"] = _now_kst()

    if source_url is not None:
        merged["source_url"] = source_url
    else:
        # source_url이 None으로 전달된 경우 기존 키를 제거하지 않음
        # (이전 병합에서 설정된 source_url은 유지)
        pass

    # 파일 저장 — 부모 디렉터리가 없으면 생성
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )

    return merged


def block_changed(path, kind: str, block: dict) -> bool:
    """기존 파일의 kind 블록과 주어진 block이 다른지 판단한다.

    Args:
        path:  확인할 파일 경로.
        kind:  블록 종류.
        block: 비교할 새 블록.

    Returns:
        True  — 파일이 없거나, kind가 없거나, 블록 값이 다를 때.
        False — 기존 블록과 완전히 동일할 때.
    """
    path = Path(path)

    if not path.exists():
        return True

    existing = _load_existing(path)

    if kind not in existing:
        return True

    old = existing[kind]
    if old == block:
        return False

    # 다운그레이드 방지: 같은 period 를 더 빈약하게(non-null 값이 더 적게) 재파싱한 결과는
    # 큐레이션된 기존 블록을 덮어쓰지 않는다. 새 회차(period 다름)·보강(값 증가)·정정(개수 동일)은 인정.
    if isinstance(old, dict) and old.get("period") == block.get("period"):
        return _count_non_null(block) >= _count_non_null(old)

    return True


def _count_non_null(obj: Any) -> int:
    """중첩 dict/list 안의 non-null 리프 값 개수."""
    if isinstance(obj, dict):
        return sum(_count_non_null(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(_count_non_null(v) for v in obj)
    return 0 if obj is None else 1
