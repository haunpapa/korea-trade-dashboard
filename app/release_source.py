"""release_source.py — 수출입 현황 보도자료 소스 탐지·수집 라이브러리.

EIEC(한국개발연구원 경제정보센터) 등 허용된 사이트에서만 수집한다.
관세청(customs.go.kr) 직접 수집은 해외 IP 차단·JS 렌더링·HWP 파일 등의
이유로 금지한다.

Public API
----------
- SourceError                       — 수집·파싱 실패 예외
- detect_kind(d: date) -> str       — 날짜로 발표 구분 추론
- pick_latest_article(list_html, target, base_url) -> str | None
- extract_body(article_html: str) -> str
- fetch_body(url, *, client, timeout) -> str
"""

from __future__ import annotations

import datetime
import re
import urllib.parse
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.release_period import ReleaseTarget

# ---------------------------------------------------------------------------
# 예외
# ---------------------------------------------------------------------------

class SourceError(Exception):
    """수집 또는 파싱 과정에서 복구 불가능한 오류가 발생했을 때 raise된다."""


# ---------------------------------------------------------------------------
# 날짜 → kind 추론
# ---------------------------------------------------------------------------

def detect_kind(d: datetime.date) -> str:
    """날짜로 수출입 현황 발표 구분을 추론한다.

    정확한 발표일:
        1일  → "monthly"  (전월 월간 실적)
        11일 → "tenday"   (당월 1~10일 실적)
        21일 → "twentyday"(당월 1~20일 실적)

    관대한 폴백 (발표 지연 대응):
        1~5일   → "monthly"
        11~15일 → "tenday"
        21~25일 → "twentyday"

    그 외 날짜는 SourceError를 발생시킨다.
    """
    day = d.day
    if 1 <= day <= 5:
        return "monthly"
    if 11 <= day <= 15:
        return "tenday"
    if 21 <= day <= 25:
        return "twentyday"
    raise SourceError(
        f"{d.isoformat()}은 알 수 없는 발표 구분입니다. "
        f"허용 범위: 1~5일(monthly), 11~15일(tenday), 21~25일(twentyday)."
    )


# ---------------------------------------------------------------------------
# 기사 목록 페이지에서 최신 기사 URL 선택
# ---------------------------------------------------------------------------

def pick_latest_article(list_html: str, target: ReleaseTarget, base_url: str) -> str | None:
    """목록 페이지 HTML에서 요청 회차 기사의 첫 번째 절대 URL을 반환한다.

    Args:
        list_html: 기사 목록 페이지 HTML 문자열.
        target:    요청된 발표 구분과 기준일. 이전 회차 기사는 선택하지 않는다.
        base_url:  상대 경로를 절대 URL로 변환할 기준 URL.

    Returns:
        첫 번째 매칭 앵커의 절대 URL, 없으면 None.
    """
    soup = BeautifulSoup(list_html, "lxml")
    articles = soup.select('a[href*="materialView.do?"]')
    if not articles:
        raise SourceError("유효한 EIEC 목록이 아닙니다 (기사 링크 없음). 차단 응답/목록 구조를 확인하세요.")
    for a in articles:
        text = a.get_text(" ", strip=True)
        compact = re.sub(r"\s+", "", text)
        if re.search(r"수출입(?:현황|동향)", compact) and target.matches_period(text):
            return urllib.parse.urljoin(base_url, a["href"])

    return None


# ---------------------------------------------------------------------------
# 기사 본문 추출
# ---------------------------------------------------------------------------

# 제거할 태그 목록
_STRIP_TAGS = {"script", "style", "nav", "header", "footer"}

# 연속 공백 압축용 정규식
_WHITESPACE_RE = re.compile(r"[ \t]+")
_MULTILINE_RE = re.compile(r"\n{3,}")


def extract_body(article_html: str) -> str:
    """기사 HTML에서 가시적 본문 텍스트를 추출한다.

    script, style, nav, header, footer 태그를 제거하고
    남은 텍스트의 과도한 공백을 정리한다.

    Args:
        article_html: 기사 페이지 HTML 문자열.

    Returns:
        정리된 가시적 본문 텍스트.
    """
    soup = BeautifulSoup(article_html, "lxml")

    # 불필요한 태그 모두 제거
    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()

    # 가시적 텍스트 추출
    raw_text = soup.get_text(separator="\n")

    # 공백 정규화
    lines = [_WHITESPACE_RE.sub(" ", line).strip() for line in raw_text.splitlines()]
    cleaned = "\n".join(line for line in lines if line)
    cleaned = _MULTILINE_RE.sub("\n\n", cleaned)

    return cleaned.strip()


# ---------------------------------------------------------------------------
# HTTP 수집
# ---------------------------------------------------------------------------

# 수집 금지 도메인
_BLOCKED_HOST_SUFFIX = "customs.go.kr"


def fetch_body(url: str, *, client=None, timeout: float = 20.0) -> str:
    """URL에서 기사 본문을 수집해 텍스트로 반환한다.

    Args:
        url:     수집할 기사 URL.
        client:  get(url, timeout=...) 메서드를 가진 httpx 호환 클라이언트.
                 None이면 httpx 모듈을 직접 사용한다.
        timeout: 요청 타임아웃(초). 기본값 20.0.

    Returns:
        extract_body()로 정리된 기사 본문 텍스트.

    Raises:
        SourceError: 차단 도메인이거나 네트워크/HTTP 오류가 발생한 경우.
    """
    # 관세청 직접 수집 금지 — 해외 IP 차단 / JS 렌더링 필요 / HWP 파일
    host = urlparse(url).hostname or ""
    if host.endswith(_BLOCKED_HOST_SUFFIX):
        raise SourceError(
            "관세청 직접 수집 금지 — 해외 IP 차단/JS/HWP. EIEC·뉴스만 허용"
        )

    # 실제 HTTP 요청
    import httpx  # noqa: PLC0415  # 지연 임포트 (테스트 격리)

    _client = client if client is not None else httpx

    try:
        resp = _client.get(url, timeout=timeout)
        resp.raise_for_status()
    except SourceError:
        raise
    except Exception as exc:
        raise SourceError(f"HTTP 수집 오류 ({url}): {exc}") from exc

    return extract_body(resp.text)
