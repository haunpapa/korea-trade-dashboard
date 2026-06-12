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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import aggregate  # noqa: E402
from app.cache import FileCache  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.customs import CustomsClient  # noqa: E402
from app.mappings import REGION_NAMES, SECTOR_GROUPS  # noqa: E402

logger = logging.getLogger("export_static")

DATA_FILES = ("monthly.json", "trend.json", "sector-trend.json", "region-trend.json", "meta.json")


def default_yymm() -> str:
    today = dt.date.today().replace(day=1) - dt.timedelta(days=1)
    return today.strftime("%Y%m")


async def collect(client: CustomsClient, end_yymm: str, months: int) -> dict[str, Any]:
    """모든 대시보드 데이터를 수집해 파일명→내용 dict로 반환."""
    logger.info("수집 시작: end=%s months=%d", end_yymm, months)
    monthly = await aggregate.build_monthly(client, end_yymm)
    trend = await aggregate.build_trend(client, end_yymm, months)
    sector_trend = {
        g: await aggregate.build_sector_trend(client, g, end_yymm, months) for g in SECTOR_GROUPS
    }
    region_trend = {
        r: await aggregate.build_region_trend(client, r, end_yymm, months) for r in REGION_NAMES
    }
    meta = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "end_yymm": end_yymm,
        "months": months,
        "source": "관세청 무역통계 API (HS 기준)",
    }
    return {
        "monthly.json": monthly,
        "trend.json": trend,
        "sector-trend.json": sector_trend,
        "region-trend.json": region_trend,
        "meta.json": meta,
    }


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
    args = parser.parse_args()

    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    if not settings.customs_service_key:
        raise SystemExit("CUSTOMS_SERVICE_KEY가 비어 있습니다 (.env 확인).")

    end = args.end or default_yymm()
    async with httpx.AsyncClient() as http:
        client = CustomsClient(settings, FileCache(settings.cache_dir), http)
        data = await collect(client, end, args.months)

    paths = write_outputs(data, Path(args.outdir))
    if args.push:
        await push_to_github(paths, settings.github_repo, settings.github_branch, settings.github_token)
        logger.info("완료 — 대시보드가 다음 로드부터 새 데이터를 사용합니다.")
    else:
        logger.info("완료 — --push 옵션으로 GitHub 업로드 가능.")


if __name__ == "__main__":
    asyncio.run(main())
