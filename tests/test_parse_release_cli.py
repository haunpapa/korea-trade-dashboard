"""tests/test_parse_release_cli.py — scripts/parse_release.py CLI 테스트.

TDD: 테스트 먼저 작성 (RED → GREEN).
네트워크·실제 API 없음 — 모두 monkeypatch.
"""
import json
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# 공유 VALID_BLOCK — test_release_parse.py와 동일한 twentyday 블록
# ---------------------------------------------------------------------------
VALID_BLOCK = {
    "tab": "1~20일 속보",
    "tabDay": "21일 발표 · 관세청",
    "granularity": "partial",
    "period": "2026년 6월 1~20일",
    "status": "순별 잠정 · 최신",
    "src": "관세청",
    "date": "2026.06.21",
    "totals": {
        "exports": 620.0,
        "exportsYoY": 60.4,
        "imports": 445.0,
        "importsYoY": 23.2,
        "balance": 175.0,
        "dailyAvg": None,
        "dailyAvgYoY": None,
    },
    "semiShare": {
        "value": 41.2,
        "label": "반도체 수출 비중",
        "note": "…",
    },
    "items": [
        {"name": "반도체", "value": 255.1, "yoy": 188.4, "star": True},
        {"name": "컴퓨터주변기기", "value": None, "yoy": 293.3},
    ],
    "regions": [],
    "note": "…",
}


# ---------------------------------------------------------------------------
# 테스트 1: 정상 경로 — --text 입력 → 파싱 → merge → exit 0
# ---------------------------------------------------------------------------
def test_text_path_success(tmp_path, monkeypatch):
    """--text 플래그로 직접 입력 시 정상 동작."""
    from app.release_parse import ReleaseParseError  # noqa: F401

    # parse_release_text → 고정 결과 반환
    monkeypatch.setattr(
        "scripts.parse_release.parse_release_text",
        lambda text, kind, client: {"twentyday": VALID_BLOCK},
    )
    # default_client → 더미 객체
    monkeypatch.setattr(
        "scripts.parse_release.default_client",
        lambda: object(),
    )

    out_file = tmp_path / "release.json"
    from scripts.parse_release import main

    result = main(["--kind", "twentyday", "--text", "dummy body", "--out", str(out_file)])

    assert result == 0
    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["twentyday"]["totals"]["exports"] == 620.0


# ---------------------------------------------------------------------------
# 테스트 2: --text / --url 모두 없으면 argparse 오류 (SystemExit)
# ---------------------------------------------------------------------------
def test_missing_text_or_url_exits(tmp_path):
    """--text / --url 없이 실행하면 argparse가 SystemExit를 발생시킨다."""
    from scripts.parse_release import main

    with pytest.raises(SystemExit):
        main(["--kind", "twentyday", "--out", str(tmp_path / "r.json")])


# ---------------------------------------------------------------------------
# 테스트 3: ReleaseParseError 발생 시 exit 2
# ---------------------------------------------------------------------------
def test_parse_error_returns_2(tmp_path, monkeypatch):
    """parse_release_text가 ReleaseParseError를 raise하면 main이 2를 반환한다."""
    from app.release_parse import ReleaseParseError

    monkeypatch.setattr(
        "scripts.parse_release.parse_release_text",
        lambda text, kind, client: (_ for _ in ()).throw(
            ReleaseParseError("파싱 실패")
        ),
    )
    monkeypatch.setattr(
        "scripts.parse_release.default_client",
        lambda: object(),
    )

    out_file = tmp_path / "release.json"
    from scripts.parse_release import main

    result = main(["--kind", "twentyday", "--text", "bad body", "--out", str(out_file)])

    assert result == 2
