"""tests/test_fetch_release_cli.py — scripts/fetch_release.py CLI 테스트.

TDD: 테스트 먼저 작성 (RED → GREEN).
네트워크·실제 API 없음 — 모두 monkeypatch.
"""
import json
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

# 캔드 리스트 HTML — pick_latest_article 이 URL을 반환하도록 할 더미 HTML
_CANNED_LIST_HTML = "<html><body><a href='/article/1'>1~20일 수출입 현황</a></body></html>"
_ARTICLE_URL = "https://eiec.kdi.re.kr/article/1"


# ---------------------------------------------------------------------------
# 헬퍼: httpx GET 을 대체하는 가짜 응답
# ---------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


class _FakeHttpxClient:
    """httpx.Client 인터페이스를 흉내내는 더미 클라이언트."""

    def __init__(self, html: str):
        self._html = html

    def get(self, url, **kwargs):
        return _FakeResponse(self._html)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


# ---------------------------------------------------------------------------
# 테스트 4: 정상 경로 — 기사 존재 → 파싱 → 쓰기 → exit 0
# ---------------------------------------------------------------------------
def test_full_pipeline_success(tmp_path, monkeypatch):
    """목록 fetch → 기사 선택 → fetch_body → 파싱 → 병합 → exit 0."""
    # httpx.Client(...)를 대체
    monkeypatch.setattr(
        "scripts.fetch_release.httpx.Client",
        lambda **kwargs: _FakeHttpxClient(_CANNED_LIST_HTML),
    )
    monkeypatch.setattr(
        "scripts.fetch_release.pick_latest_article",
        lambda html, kind, base_url: _ARTICLE_URL,
    )
    monkeypatch.setattr(
        "scripts.fetch_release.fetch_body",
        lambda url, **kwargs: "기사 본문 텍스트",
    )
    monkeypatch.setattr(
        "scripts.fetch_release.parse_release_text",
        lambda text, kind, client: {"twentyday": VALID_BLOCK},
    )
    monkeypatch.setattr(
        "scripts.fetch_release.default_client",
        lambda: object(),
    )

    out_file = tmp_path / "release.json"
    from scripts.fetch_release import main

    result = main(["--date", "2026-06-21", "--out", str(out_file)])

    assert result == 0
    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["twentyday"]["totals"]["exports"] == 620.0


# ---------------------------------------------------------------------------
# 테스트 5: 기사 없음 → exit 2, 파일 미생성
# ---------------------------------------------------------------------------
def test_no_article_returns_2(tmp_path, monkeypatch):
    """pick_latest_article이 None을 반환하면 exit 2, 파일 미생성."""
    monkeypatch.setattr(
        "scripts.fetch_release.httpx.Client",
        lambda **kwargs: _FakeHttpxClient(_CANNED_LIST_HTML),
    )
    monkeypatch.setattr(
        "scripts.fetch_release.pick_latest_article",
        lambda html, kind, base_url: None,
    )

    out_file = tmp_path / "release.json"
    from scripts.fetch_release import main

    result = main(["--date", "2026-06-21", "--out", str(out_file)])

    assert result == 2
    assert not out_file.exists()


# ---------------------------------------------------------------------------
# 테스트 6: 변경 없음(no-op) → exit 0, 파일 내용 유지
# ---------------------------------------------------------------------------
def test_no_op_when_block_unchanged(tmp_path, monkeypatch):
    """기존 파일과 동일한 블록이면 쓰기 없이 exit 0."""
    out_file = tmp_path / "release.json"

    # 기존 파일에 동일 블록 사전 기록
    initial = {
        "twentyday": VALID_BLOCK,
        "generated_at": "2026-06-21T10:00:00+09:00",
    }
    out_file.write_text(
        json.dumps(initial, ensure_ascii=False), encoding="utf-8"
    )

    mtime_before = out_file.stat().st_mtime

    monkeypatch.setattr(
        "scripts.fetch_release.httpx.Client",
        lambda **kwargs: _FakeHttpxClient(_CANNED_LIST_HTML),
    )
    monkeypatch.setattr(
        "scripts.fetch_release.pick_latest_article",
        lambda html, kind, base_url: _ARTICLE_URL,
    )
    monkeypatch.setattr(
        "scripts.fetch_release.fetch_body",
        lambda url, **kwargs: "기사 본문 텍스트",
    )
    monkeypatch.setattr(
        "scripts.fetch_release.parse_release_text",
        lambda text, kind, client: {"twentyday": VALID_BLOCK},
    )
    monkeypatch.setattr(
        "scripts.fetch_release.default_client",
        lambda: object(),
    )

    from scripts.fetch_release import main

    result = main(["--date", "2026-06-21", "--out", str(out_file)])

    assert result == 0
    # 파일이 변경되지 않았는지 확인 (mtime 비교)
    mtime_after = out_file.stat().st_mtime
    assert mtime_after == mtime_before, "no-op인데 파일이 재작성됐습니다"


# ---------------------------------------------------------------------------
# 회귀: GitHub Actions는 미설정 vars 를 빈 문자열로 넘긴다.
# RELEASE_SOURCE_LIST_URL="" 이면 기본 EIEC URL을 써야 한다(빈 URL로 요청 금지).
# ---------------------------------------------------------------------------
def test_empty_source_url_env_falls_back_to_default(tmp_path, monkeypatch):
    """RELEASE_SOURCE_LIST_URL 이 빈 문자열이면 _DEFAULT_LIST_URL 로 목록을 요청한다."""
    from scripts import fetch_release

    requested: list[str] = []

    class _RecordingClient(_FakeHttpxClient):
        def get(self, url, **kwargs):
            requested.append(url)
            return super().get(url, **kwargs)

    monkeypatch.setenv("RELEASE_SOURCE_LIST_URL", "")
    monkeypatch.setattr(
        "scripts.fetch_release.httpx.Client",
        lambda **kwargs: _RecordingClient(_CANNED_LIST_HTML),
    )
    monkeypatch.setattr(
        "scripts.fetch_release.pick_latest_article",
        lambda html, kind, base_url: _ARTICLE_URL,
    )
    monkeypatch.setattr("scripts.fetch_release.fetch_body", lambda url, **kwargs: "본문")
    monkeypatch.setattr(
        "scripts.fetch_release.parse_release_text",
        lambda text, kind, client: {"twentyday": VALID_BLOCK},
    )
    monkeypatch.setattr("scripts.fetch_release.default_client", lambda: object())

    out_file = tmp_path / "release.json"
    result = fetch_release.main(["--date", "2026-06-21", "--out", str(out_file)])

    assert result == 0
    assert requested == [fetch_release._DEFAULT_LIST_URL]
