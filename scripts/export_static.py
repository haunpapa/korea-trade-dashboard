"""로컬 PC에서 관세청 데이터를 수집해 정적 JSON으로 내보내는 스크립트.

data.go.kr은 해외 IP를 차단하므로(403) 이 스크립트는 **한국 IP의 로컬 PC**에서 실행합니다.
생성된 data/*.json을 GitHub에 올리면 대시보드가 어디서든(라즈베리·Railway·Pages·file://)
raw.githubusercontent.com 에서 읽어 자동 갱신됩니다.

사용법
  python scripts/export_static.py            # data/ 폴더에 JSON 생성만
  python scripts/export_static.py --push     # 생성 + GitHub 업로드 (.env의 GITHUB_TOKEN 필요)
  python scripts/export_static.py --months 24 --end 202605

.env 설정 (push용)
  GITHUB_TOKEN=github_pat_...   # fine-grained, 해당 레포 Contents: Read/Write만
  GITHUB_REPO=haunpapa/korea-trade-dashboard
"""

import argparse
import asyncio
import base64
import datetime as dt
import json
import logging
import sys
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.cache import FileCache  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.customs import CustomsClient  # noqa: E402

logger = logging.getLogger("export_static")

DATA_FILES = (
    "monthly.json", "trend.json", "sector-trend.json", "region-trend.json",
    "item-trend.json", "item-countries.json", "fx.json", "meta.json",
)


def default_yymm() -> str:
    today = dt.date.today().replace(day=1) - dt.timedelta(days=1)
    return today.strftime("%Y%m")


# collect는 app.exporter와 단일 구현을 공유합니다.
from app.exporter import collect  # noqa: E402


def load_prior(outdir: Path) -> dict[str, Any] | None:
    """outdir 의 이전 산출물을 읽는다. trend.json 이 없거나 깨졌으면 None(전체 수집)."""
    out: dict[str, Any] = {}
    for name in DATA_FILES:
        p = outdir / name
        if not p.exists():
            continue
        try:
            out[name] = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("이전 산출물 %s 읽기 실패(%s) — 무시", p, exc)
    return out if isinstance(out.get("trend.json"), list) and out["trend.json"] else None


def write_outputs(data: dict[str, Any], outdir: Path) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, content in data.items():
        p = outdir / name
        p.write_text(json.dumps(content, ensure_ascii=False, indent=1), encoding="utf-8")
        logger.info("저장: %s (%d bytes)", p, p.stat().st_size)
        paths.append(p)
    return paths


async def push_to_github(paths: list[Path], repo: str, branch: str, token: str) -> None:
    """GitHub contents API로 data/ 파일 업로드 (git 설치 불필요)."""
    if not token:
        raise SystemExit("GITHUB_TOKEN이 비어 있습니다. .env에 추가하세요 (--push 생략 시 로컬 저장만).")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    async with httpx.AsyncClient(headers=headers, timeout=30) as http:
        for p in paths:
            url = f"https://api.github.com/repos/{repo}/contents/data/{p.name}"
            sha = None
            r = await http.get(url, params={"ref": branch})
            if r.status_code == 200:
                sha = r.json().get("sha")
            body = {
                "message": f"data: {p.name} 갱신 (자동 수집)",
                "content": base64.b64encode(p.read_bytes()).decode(),
                "branch": branch,
                **({"sha": sha} if sha else {}),
            }
            r = await http.put(url, json=body)
            if r.status_code not in (200, 201):
                raise SystemExit(f"업로드 실패 {p.name}: HTTP {r.status_code} {r.text[:200]}")
            logger.info("업로드 완료: data/%s", p.name)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--end", default=None, help="기준 년월 YYYYMM (기본: 직전 달)")
    parser.add_argument("--months", type=int, default=12, help="추세 개월 수 (기본 12)")
    parser.add_argument("--push", action="store_true", help="GitHub data/ 폴더로 업로드")
    parser.add_argument("--outdir", default=str(ROOT / "data"), help="출력 폴더")
    parser.add_argument("--full", action="store_true",
                        help="증분 수집 끄기 — outdir 의 이전 산출물을 무시하고 12개월 전체 재수집")
    parser.add_argument("--refresh-recent", type=int, default=1, metavar="N",
                        help="증분 모드에서 이전 산출물에 있어도 다시 긁을 최근 N개월 (기본 1, 잠정→확정)")
    args = parser.parse_args()

    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # 요청 URL(serviceKey 포함) 로그 방지
    settings = get_settings()
    if not settings.customs_service_key:
        raise SystemExit("CUSTOMS_SERVICE_KEY가 비어 있습니다 (.env 확인).")

    end = args.end or default_yymm()
    prior = None if args.full else load_prior(Path(args.outdir))
    if prior:
        logger.info("증분 모드: %s 의 이전 산출물(end=%s) 재사용, 최근 %d개월 재수집",
                    args.outdir, prior.get("meta.json", {}).get("end_yymm"), args.refresh_recent)
    async with httpx.AsyncClient() as http:
        client = CustomsClient(settings, FileCache(settings.cache_dir), http)
        try:
            data = await collect(client, end, args.months, prior=prior, refresh_recent=args.refresh_recent)
        except HTTPException as exc:
            # traceback 은 요청 URL(serviceKey 포함)을 노출하므로 메시지만 출력하고 종료.
            # 이미 성공한 (월,HS) 는 _cache/ 에 남아 다음 실행에서 이어서 수집된다.
            cached = len(list(Path(settings.cache_dir).glob("*.json")))
            raise SystemExit(f"수집 중단: {exc.detail} (캐시 {cached}건 보존 — 재실행 시 이어서 수집)") from None

    paths = write_outputs(data, Path(args.outdir))
    if args.push:
        await push_to_github(paths, settings.github_repo, settings.github_branch, settings.github_token)
        logger.info("완료 — 대시보드가 다음 로드부터 새 데이터를 사용합니다.")
    else:
        logger.info("완료 — --push 옵션으로 GitHub 업로드 가능.")


if __name__ == "__main__":
    asyncio.run(main())
