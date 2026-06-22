"""parse_release.py — 수동 폴백: 보도자료 텍스트/URL → 파싱 → release.json 병합.

사용법
------
  # 직접 텍스트 붙여넣기
  python scripts/parse_release.py --kind twentyday --text "$(cat body.txt)"

  # URL에서 본문 수집
  python scripts/parse_release.py --kind monthly --url https://eiec.kdi.re.kr/...

옵션
----
  --kind {monthly,tenday,twentyday}  필수. 발표 구분.
  --text TEXT                        보도자료 본문을 직접 전달 (--url과 상호 배타).
  --url URL                          기사 URL (release_source.fetch_body로 수집).
  --out PATH                         출력 JSON 파일 경로 (기본: data/release.json).

종료 코드
---------
  0 — 성공
  2 — 파싱 오류 또는 수집 오류
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# 레포 루트를 sys.path에 추가하여 app.*·scripts.* 임포트 가능하게 함
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.release_parse import ReleaseParseError, default_client, parse_release_text  # noqa: E402
from app.release_source import SourceError, fetch_body  # noqa: E402
from app.release_store import merge_release_block  # noqa: E402

logger = logging.getLogger("parse_release")

# 기본 출력 경로
_DEFAULT_OUT = ROOT / "data" / "release.json"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--kind",
        choices=["monthly", "tenday", "twentyday"],
        required=True,
        help="발표 구분 (월간/10일/20일)",
    )
    parser.add_argument(
        "--out",
        default=str(_DEFAULT_OUT),
        help="출력 JSON 파일 경로 (기본: data/release.json)",
    )

    # --text / --url 중 하나 필수 (상호 배타)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", metavar="TEXT", help="보도자료 본문을 직접 전달")
    group.add_argument("--url", metavar="URL", help="기사 URL (fetch_body로 수집)")

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점. 테스트에서 argv를 주입할 수 있도록 main(argv=None) 형태로 작성.

    Returns:
        0 — 성공, 2 — 오류
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = _build_parser()
    args = parser.parse_args(argv)

    kind: str = args.kind
    out: str = args.out
    url: str | None = args.url

    # 본문 취득
    try:
        if args.text is not None:
            body = args.text
            source_label = "manual paste"
        else:
            # URL에서 본문 수집
            logger.info("URL에서 본문 수집 중: %s", url)
            body = fetch_body(url)
            source_label = url
    except SourceError as exc:
        print(f"수집 오류: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"예상치 못한 수집 오류: {exc}", file=sys.stderr)
        return 2

    # LLM 파싱
    try:
        client = default_client()
        parsed = parse_release_text(body, kind, client=client)
    except ReleaseParseError as exc:
        print(f"파싱 오류: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"예상치 못한 파싱 오류: {exc}", file=sys.stderr)
        return 2

    # release.json에 병합
    block = parsed[kind]
    merged = merge_release_block(out, kind, block, source_url=source_label)

    # 성공 요약 출력
    totals = block.get("totals", {})
    exports = totals.get("exports")
    items = block.get("items", [])
    semi = next((i for i in items if "반도체" in i.get("name", "")), None)
    semi_val = semi.get("value") if semi else None

    print(
        f"[parse_release] 완료 — kind={kind}, "
        f"수출={exports}억달러, 반도체={semi_val}억달러, "
        f"out={out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
