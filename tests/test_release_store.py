"""test_release_store.py — release_store 모듈 단위 테스트 (TDD: 먼저 작성)."""

import json
from pathlib import Path

import pytest

from app.release_store import block_changed, merge_release_block

# ---------------------------------------------------------------------------
# 샘플 블록 (간소화된 더미 데이터)
# ---------------------------------------------------------------------------

_SAMPLE_BLOCK = {
    "tab": "6월",
    "tabDay": "20일",
    "granularity": "twentyday",
    "period": "2026.06.01~20",
    "status": "잠정",
    "src": "산업통상자원부",
    "date": "2026-06-22",
    "totals": {
        "exports": 620.0,
        "exportsYoY": 8.7,
        "imports": 542.0,
        "importsYoY": 3.2,
        "balance": 78.0,
        "dailyAvg": None,
        "dailyAvgYoY": None,
    },
    "semiShare": {"value": 41.1, "label": "반도체", "note": "전체 수출의 41.1%"},
    "items": [],
    "regions": [],
    "note": "잠정치",
}

_MODIFIED_BLOCK = {**_SAMPLE_BLOCK, "note": "수정된 잠정치"}


# ---------------------------------------------------------------------------
# 테스트 1: 존재하지 않는 경로에 병합하면 파일이 생성됨
# ---------------------------------------------------------------------------

def test_merge_creates_file_when_not_exists(tmp_path):
    """존재하지 않는 경로에 merge_release_block 호출 시 파일을 생성한다."""
    target = tmp_path / "release.json"
    result = merge_release_block(target, "twentyday", _SAMPLE_BLOCK)

    # 반환값에 kind 블록과 generated_at이 있어야 함
    assert "twentyday" in result
    assert "generated_at" in result
    assert result["twentyday"] == _SAMPLE_BLOCK

    # 파일이 실제로 생성됐는지 확인
    assert target.exists()
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["twentyday"] == _SAMPLE_BLOCK
    assert "generated_at" in on_disk


# ---------------------------------------------------------------------------
# 테스트 2: 서로 다른 kind를 두 번 병합하면 둘 다 유지됨 (부분 업데이트)
# ---------------------------------------------------------------------------

_TENDAY_BLOCK = {
    "tab": "6월",
    "tabDay": "10일",
    "granularity": "tenday",
    "period": "2026.06.01~10",
    "status": "잠정",
    "src": "산업통상자원부",
    "date": "2026-06-11",
    "totals": {
        "exports": 300.0,
        "exportsYoY": 5.0,
        "imports": 280.0,
        "importsYoY": 2.0,
        "balance": 20.0,
        "dailyAvg": None,
        "dailyAvgYoY": None,
    },
    "workdays": {"now": 8.0, "prev": 8.0},
    "items": [],
    "regions": [],
    "note": "잠정치",
}


def test_merge_preserves_other_kinds(tmp_path):
    """두 번째 병합 시 첫 번째 kind 블록이 그대로 유지된다."""
    target = tmp_path / "release.json"

    # 첫 번째 병합: twentyday
    merge_release_block(target, "twentyday", _SAMPLE_BLOCK)
    # 두 번째 병합: tenday
    result = merge_release_block(target, "tenday", _TENDAY_BLOCK)

    # 두 kind가 모두 존재해야 함
    assert "twentyday" in result
    assert "tenday" in result
    assert result["twentyday"] == _SAMPLE_BLOCK
    assert result["tenday"] == _TENDAY_BLOCK

    # 디스크에도 동일하게 기록돼 있어야 함
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert "twentyday" in on_disk
    assert "tenday" in on_disk


# ---------------------------------------------------------------------------
# 테스트 3: block_changed — 동일 블록이면 False, 다른 블록이면 True
# ---------------------------------------------------------------------------

def test_block_changed_false_when_identical(tmp_path):
    """병합 후 동일 블록으로 block_changed 호출하면 False를 반환한다."""
    target = tmp_path / "release.json"
    merge_release_block(target, "twentyday", _SAMPLE_BLOCK)

    # 동일 블록 → 변경 없음
    assert block_changed(target, "twentyday", _SAMPLE_BLOCK) is False


def test_block_changed_true_when_different(tmp_path):
    """블록 내용이 다르면 block_changed가 True를 반환한다."""
    target = tmp_path / "release.json"
    merge_release_block(target, "twentyday", _SAMPLE_BLOCK)

    # 다른 블록 → 변경 있음
    assert block_changed(target, "twentyday", _MODIFIED_BLOCK) is True


def test_block_changed_true_when_file_missing(tmp_path):
    """파일이 없으면 block_changed가 True를 반환한다."""
    target = tmp_path / "nonexistent.json"
    assert block_changed(target, "twentyday", _SAMPLE_BLOCK) is True


def test_block_changed_true_when_kind_missing(tmp_path):
    """파일이 있지만 해당 kind가 없으면 block_changed가 True를 반환한다."""
    target = tmp_path / "release.json"
    merge_release_block(target, "tenday", _TENDAY_BLOCK)

    # "twentyday"는 아직 없음
    assert block_changed(target, "twentyday", _SAMPLE_BLOCK) is True


# ---------------------------------------------------------------------------
# 테스트 4: 입력 block dict가 변경되지 않아야 함 (불변성)
# ---------------------------------------------------------------------------

def test_merge_does_not_mutate_input_block(tmp_path):
    """merge_release_block이 입력 block dict를 변경하지 않는다."""
    target = tmp_path / "release.json"
    original_keys = set(_SAMPLE_BLOCK.keys())
    original_note = _SAMPLE_BLOCK["note"]

    merge_release_block(target, "twentyday", _SAMPLE_BLOCK)

    # 원본 dict의 키와 값이 그대로여야 함
    assert set(_SAMPLE_BLOCK.keys()) == original_keys
    assert _SAMPLE_BLOCK["note"] == original_note


# ---------------------------------------------------------------------------
# 테스트 5: source_url 옵션 — 제공 시 데이터에 포함
# ---------------------------------------------------------------------------

def test_merge_includes_source_url_when_provided(tmp_path):
    """source_url 제공 시 반환된 dict와 파일에 source_url이 포함된다."""
    target = tmp_path / "release.json"
    url = "https://eiec.kdi.re.kr/policy/materialView.do?num=282600"
    result = merge_release_block(target, "twentyday", _SAMPLE_BLOCK, source_url=url)

    assert result.get("source_url") == url

    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk.get("source_url") == url


def test_merge_no_source_url_by_default(tmp_path):
    """source_url 미제공 시 반환된 dict에 source_url 키가 없다."""
    target = tmp_path / "release.json"
    result = merge_release_block(target, "twentyday", _SAMPLE_BLOCK)

    assert "source_url" not in result


# ---------------------------------------------------------------------------
# 다운그레이드 방지 (2026-08-17): 같은 period 를 더 빈약하게 재파싱한 블록은 변경으로 보지 않는다
# ---------------------------------------------------------------------------
def _sparser(block: dict) -> dict:
    """같은 period, 총괄만 남고 상세는 null 인 블록."""
    return {
        **block,
        "totals": {**block["totals"], "dailyAvg": None, "dailyAvgYoY": None},
        "items": [{"name": "반도체", "value": None, "yoy": None}],
        "note": "요약문 기반 재파싱",
    }


def test_block_changed_false_when_same_period_but_sparser(tmp_path):
    """동일 period 인데 non-null 값이 더 적은 블록은 no-op(다운그레이드 방지)."""
    from app.release_store import block_changed, merge_release_block

    path = tmp_path / "release.json"
    rich = {**_SAMPLE_BLOCK, "period": "2026년 8월 1~10일",
            "totals": {**_SAMPLE_BLOCK["totals"], "dailyAvg": 30.4, "dailyAvgYoY": 45.3},
            "items": [{"name": "반도체", "value": 99.5, "yoy": 155.4}]}
    merge_release_block(path, "tenday", rich)

    assert block_changed(path, "tenday", _sparser(rich)) is False


def test_block_changed_true_when_new_period_even_if_sparser(tmp_path):
    """period 가 다르면(새 회차) 빈약해도 변경으로 인정한다."""
    from app.release_store import block_changed, merge_release_block

    path = tmp_path / "release.json"
    rich = {**_SAMPLE_BLOCK, "period": "2026년 8월 1~10일",
            "items": [{"name": "반도체", "value": 99.5, "yoy": 155.4}]}
    merge_release_block(path, "tenday", rich)

    newer = {**_sparser(rich), "period": "2026년 8월 1~20일"}
    assert block_changed(path, "tenday", newer) is True


def test_block_changed_true_when_same_period_and_richer(tmp_path):
    """동일 period 라도 non-null 값이 더 많아지면(보강) 변경으로 인정한다."""
    from app.release_store import block_changed, merge_release_block

    path = tmp_path / "release.json"
    sparse = {**_SAMPLE_BLOCK, "period": "2026년 8월 1~10일",
              "items": [{"name": "반도체", "value": None, "yoy": None}]}
    merge_release_block(path, "tenday", sparse)

    richer = {**sparse, "items": [{"name": "반도체", "value": 99.5, "yoy": 155.4}]}
    assert block_changed(path, "tenday", richer) is True
