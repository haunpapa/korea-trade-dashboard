"""파일 기반 영구 캐시 — 월간 확정 통계는 불변이므로 영구 보존, ?refresh=1로 무효화."""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FileCache:
    """JSON 파일 캐시. 키 1개 = 파일 1개."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in key)
        return self.cache_dir / f"{safe}.json"

    def get(self, key: str) -> Any | None:
        p = self._path(key)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("손상된 캐시 파일 무시: %s", p)
            return None

    def set(self, key: str, value: Any) -> None:
        try:
            self._path(key).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        except OSError:
            logger.warning("캐시 쓰기 실패: %s", key, exc_info=True)

    def stats(self) -> dict[str, int]:
        files = list(self.cache_dir.glob("*.json"))
        return {"entries": len(files), "bytes": sum(f.stat().st_size for f in files)}
