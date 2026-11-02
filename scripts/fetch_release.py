"""fetch_release.py — 자동 수집: 날짜 → 소스 목록 → 기사 선택 → 파싱 → release.json 병합.

CI/cron 환경에서 실행되는 완전 자동 스크립트.
기사가 없거나 블록이 변경되지 않으면 파일을 쓰지 않는다.

사용법
------
  python scripts/fetch_release.py                     # 오늘(KST) 기준
  python scripts/fetch_release.py --date 2026-06-21  # 날짜 지정
  python scripts/fetch_release.py --kind twentyday    # kind 강제 지정

옵션
----
  --date YYYY-MM-DD   기준 날짜 (기본: 오늘 KST).
  --kind {monthly,tenday,twentyday}
                      발표 구분 강제 지정 (기본: detect_kind(date)로 자동 추론).
  --out PATH          출력 JSON 파일 경로 (기본: data/release.json).

환경 변수
---------
  RELEASE_SOURCE_LIST_URL  목록 페이지 URL
                           (기본: EIEC의 수출입 검색 목록, 첫 20건)
                           # 접근 오류 HTML과 정상 목록을 구분한다.
                           # 기사 미게재/목록 첫 페이지 미노출이면 다음 실행에서 재시도한다.

종료 코드
---------
  0 — 성공 (업데이트 완료 또는 변경 없음 no-op)
  2 — 하드 실패 (수집 오류, 비정상 목록, 파싱 오류, 검증 오류)
"""

from __future__ import annotations

import argparse
import datetime
import logging
import os
import sys
from datetime import timedelta, timezone
from pathlib import Path

# 레포 루트를 sys.path에 추가하여 app.* 임포트 가능하게 함
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.release_parse import ReleaseParseError, default_client, parse_release_text  # noqa: E402
from app.release_period import ReleaseTarget  # noqa: E402
from app.release_source import (  # noqa: E402
    SourceError,
    detect_kind,
    fetch_body,
    pick_latest_article,
)
from app.release_store import block_changed, merge_release_block  # noqa: E402

logger = logging.getLogger("fetch_release")

# 일반 정책 목록에 발표가 묻히지 않도록 실제 EIEC 검색 폼을 사용한다.
_DEFAULT_LIST_URL = "https://eiec.kdi.re.kr/policy/materialList.do?type=A&search_txt=수출입&pg=1&pp=20"

# 기본 출력 경로
_DEFAULT_OUT = ROOT / "data" / "release.json"

# KST 시간대
_KST = timezone(timedelta(hours=9))


def _today_kst() -> datetime.date:
    """현재 KST 날짜를 반환한다."""
    return datetime.datetime.now(_KST).date()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        default=None,
        help="기준 날짜 (기본: 오늘 KST)",
    )
    parser.add_argument(
        "--kind",
        choices=["monthly", "tenday", "twentyday"],
        default=None,
        help="발표 구분 강제 지정 (기본: 날짜로 자동 추론)",
    )
    parser.add_argument(
        "--out",
        default=str(_DEFAULT_OUT),
        help="출력 JSON 파일 경로 (기본: data/release.json)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점. 테스트에서 argv를 주입할 수 있도록 main(argv=None) 형태로 작성.

    Returns:
        0 — 성공 (업데이트 또는 no-op)
        2 — 하드 실패
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = _build_parser()
    args = parser.parse_args(argv)

    out: str = args.out

    # 날짜 파싱
    if args.date is not None:
        try:
            date = datetime.date.fromisoformat(args.date)
        except ValueError as exc:
            print(f"날짜 형식 오류: {exc}", file=sys.stderr)
            return 2
    else:
        date = _today_kst()

    # kind 결정: 강제 지정 또는 날짜 자동 추론
    if args.kind is not None:
        kind = args.kind
    else:
        try:
            kind = detect_kind(date)
        except SourceError as exc:
            print(f"kind 추론 오류: {exc}", file=sys.stderr)
            return 2

    logger.info("처리 시작 — date=%s, kind=%s", date.isoformat(), kind)

    # 소스 목록 URL 결정
    # GitHub Actions는 미설정 vars 를 빈 문자열로 넘기므로 `or` 로 기본값 폴백
    list_url = os.environ.get("RELEASE_SOURCE_LIST_URL") or _DEFAULT_LIST_URL

    # 목록 페이지 원본 HTML 수집 (앵커 파싱용 — fetch_body가 아닌 raw HTML 필요)
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(list_url)
            resp.raise_for_status()
            list_html = resp.text
    except Exception as exc:
        print(f"목록 페이지 수집 오류 ({list_url}): {exc}", file=sys.stderr)
        return 2

    # 요청한 회차만 선택한다. HTTP 200 오류 페이지를 미발표로 취급하지 않는다.
    target = ReleaseTarget(kind, date)
    try:
        article_url = pick_latest_article(list_html, target, base_url=list_url)
    except SourceError as exc:
        logger.error("목록 검증 실패: %s", exc)
        return 2
    if article_url is None:
        logger.info("해당 회차 미게재(no-op) — date=%s, kind=%s", date, kind)
        return 0

    logger.info("기사 URL: %s", article_url)

    # 기사 본문 수집 (텍스트로 정리)
    try:
        body = fetch_body(article_url)
    except SourceError as exc:
        print(f"기사 본문 수집 오류: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"예상치 못한 수집 오류: {exc}", file=sys.stderr)
        return 2

    # LLM 파싱
    try:
        llm_client = default_client()
        parsed = parse_release_text(body, kind, client=llm_client)
    except ReleaseParseError as exc:
        print(f"파싱 오류: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"예상치 못한 파싱 오류: {exc}", file=sys.stderr)
        return 2

    block = parsed[kind]
    if not target.matches_period(block["period"]) or not target.matches_publication_date(block["date"]):
        logger.error("파싱된 발표 회차/발표일 불일치 — period=%s, date=%s", block["period"], block["date"])
        return 2

    # 변경 여부 확인 — 동일하면 no-op (파일 미기록)
    if not block_changed(out, kind, block):
        logger.info("변경 없음(no-op) — kind=%s, out=%s", kind, out)
        return 0

    # 파일 병합 (변경된 경우에만)
    merge_release_block(out, kind, block, source_url=article_url)

    totals = block.get("totals", {})
    exports = totals.get("exports")
    logger.info(
        "완료 — kind=%s, 수출=%s억달러, out=%s",
        kind, exports, out,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
