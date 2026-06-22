"""test_release_source.py — release_source 모듈 단위 테스트 (TDD: 먼저 작성).

모든 테스트는 네트워크 호출 없이 동작한다.
"""

import datetime
from pathlib import Path

import httpx
import pytest

from app.release_source import (
    SourceError,
    detect_kind,
    extract_body,
    fetch_body,
    pick_latest_article,
)

# ---------------------------------------------------------------------------
# 픽스처 경로
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"


def _read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 테스트 5: detect_kind
# ---------------------------------------------------------------------------

def test_detect_kind_monthly():
    """1일은 monthly를 반환한다."""
    assert detect_kind(datetime.date(2026, 6, 1)) == "monthly"


def test_detect_kind_tenday():
    """11일은 tenday를 반환한다."""
    assert detect_kind(datetime.date(2026, 6, 11)) == "tenday"


def test_detect_kind_twentyday():
    """21일은 twentyday를 반환한다."""
    assert detect_kind(datetime.date(2026, 6, 21)) == "twentyday"


def test_detect_kind_tolerant_monthly():
    """1~5일 범위는 monthly 허용 (관대한 폴백)."""
    assert detect_kind(datetime.date(2026, 6, 3)) == "monthly"


def test_detect_kind_tolerant_tenday():
    """11~15일 범위는 tenday 허용 (관대한 폴백)."""
    assert detect_kind(datetime.date(2026, 6, 13)) == "tenday"


def test_detect_kind_tolerant_twentyday():
    """21~25일 범위는 twentyday 허용 (관대한 폴백)."""
    assert detect_kind(datetime.date(2026, 6, 23)) == "twentyday"


def test_detect_kind_raises_for_ambiguous_day():
    """8일처럼 어떤 범위에도 속하지 않는 날짜는 SourceError를 발생시킨다."""
    with pytest.raises(SourceError):
        detect_kind(datetime.date(2026, 6, 8))


def test_detect_kind_raises_for_day_30():
    """30일은 어떤 범위에도 속하지 않아 SourceError를 발생시킨다."""
    with pytest.raises(SourceError):
        detect_kind(datetime.date(2026, 6, 30))


# ---------------------------------------------------------------------------
# 테스트 6: pick_latest_article — twentyday
# ---------------------------------------------------------------------------

def test_pick_latest_article_twentyday():
    """twentyday kind에 맞는 기사 앵커의 절대 URL을 반환한다."""
    html = _read_fixture("eiec_list.html")
    base = "https://eiec.kdi.re.kr"
    url = pick_latest_article(html, "twentyday", base)

    assert url is not None
    assert "materialView" in url
    assert url.startswith("https://eiec.kdi.re.kr")


def test_pick_latest_article_tenday():
    """tenday kind에 맞는 기사(1~10일) 앵커의 절대 URL을 반환한다."""
    html = _read_fixture("eiec_list.html")
    base = "https://eiec.kdi.re.kr"
    url = pick_latest_article(html, "tenday", base)

    assert url is not None
    assert "materialView" in url
    assert url.startswith("https://eiec.kdi.re.kr")


# ---------------------------------------------------------------------------
# 테스트 7: pick_latest_article — monthly (해당 기사 없음 → None)
# ---------------------------------------------------------------------------

def test_pick_latest_article_monthly_returns_none():
    """픽스처에 monthly 기사가 없으면 None을 반환한다."""
    html = _read_fixture("eiec_list.html")
    base = "https://eiec.kdi.re.kr"
    url = pick_latest_article(html, "monthly", base)

    assert url is None


# ---------------------------------------------------------------------------
# 테스트 8: extract_body
# ---------------------------------------------------------------------------

def test_extract_body_contains_key_text():
    """기사 본문에서 '620억'이 추출된다."""
    html = _read_fixture("eiec_article.html")
    text = extract_body(html)

    assert "620억" in text


def test_extract_body_strips_script_tags():
    """추출된 텍스트에 <script 태그가 포함되지 않는다."""
    html = _read_fixture("eiec_article.html")
    text = extract_body(html)

    assert "<script" not in text


def test_extract_body_strips_nav():
    """추출된 텍스트에 nav 내용('메뉴')이 포함되지 않는다."""
    html = _read_fixture("eiec_article.html")
    text = extract_body(html)

    assert "메뉴" not in text


def test_extract_body_strips_footer():
    """추출된 텍스트에 footer 내용이 포함되지 않는다."""
    html = _read_fixture("eiec_article.html")
    text = extract_body(html)

    assert "저작권 안내" not in text


def test_extract_body_contains_semiconductor():
    """반도체 관련 수치도 추출된다."""
    html = _read_fixture("eiec_article.html")
    text = extract_body(html)

    assert "255.1억" in text


# ---------------------------------------------------------------------------
# 테스트 9: fetch_body — 관세청 도메인 가드 (네트워크 호출 없음)
# ---------------------------------------------------------------------------

def test_fetch_body_raises_for_customs_domain():
    """customs.go.kr 도메인 URL은 SourceError를 발생시킨다 (네트워크 미호출)."""
    with pytest.raises(SourceError, match="관세청"):
        fetch_body("https://www.customs.go.kr/api/trade/monthly")


def test_fetch_body_raises_for_customs_subdomain():
    """customs.go.kr 서브도메인도 SourceError를 발생시킨다."""
    with pytest.raises(SourceError, match="관세청"):
        fetch_body("https://unipass.customs.go.kr/data")


# ---------------------------------------------------------------------------
# 테스트 10: fetch_body — httpx 클라이언트 주입 (mock)
# ---------------------------------------------------------------------------

class _MockResponse:
    """최소한의 httpx 응답 mock."""

    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=None, response=None  # type: ignore[arg-type]
            )


class _MockClient:
    """get() 메서드를 가진 최소 mock 클라이언트."""

    def __init__(self, html: str):
        self._html = html

    def get(self, url: str, **kwargs):
        return _MockResponse(self._html)


def test_fetch_body_with_mock_client():
    """주입된 mock 클라이언트를 사용해 fetch_body가 정상 동작한다."""
    html = _read_fixture("eiec_article.html")
    client = _MockClient(html)

    text = fetch_body("https://eiec.kdi.re.kr/policy/materialView.do?num=282600", client=client)

    assert "620억" in text
    assert "<script" not in text


def test_fetch_body_wraps_http_error_in_source_error():
    """HTTP 4xx/5xx 오류는 SourceError로 감싸진다."""

    class _ErrorClient:
        def get(self, url: str, **kwargs):
            return _MockResponse("", status_code=404)

    with pytest.raises(SourceError):
        fetch_body("https://eiec.kdi.re.kr/policy/materialView.do?num=0", client=_ErrorClient())
