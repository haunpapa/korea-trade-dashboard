"""환경설정 — .env 파일 및 환경변수 로딩 (pydantic-settings)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """서비스 전역 설정. 환경변수 또는 .env로 주입."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # data.go.kr '관세청_품목별 국가별 수출입실적' 일반 인증키 (Decoding 키)
    customs_service_key: str = ""
    base_url: str = "http://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList"

    cache_dir: Path = Path("./_cache")
    concurrency: int = 8
    rows_per_page: int = 999  # API 페이지당 행 수
    max_pages: int = 50  # 안전 상한
    request_timeout: float = 20.0
    retries: int = 3  # 일시 오류 재시도 횟수
    retry_backoff: float = 1.5  # 지수 백오프 계수(초)

    allow_origins: str = "*"  # 콤마 구분 목록
    log_level: str = "INFO"

    # 한국수출입은행 환율 API (koreaexim.go.kr 발급) — 추세 차트 환율 오버레이용
    exim_api_key: str = ""

    # 정적 데이터 업로드 (scripts/export_static.py --push, 서버 자동 export)
    github_token: str = ""  # fine-grained PAT, Contents: Read/Write
    github_repo: str = "haunpapa/korea-trade-dashboard"
    github_branch: str = "main"

    # 서버(Railway) 일일 자동 export — 매일 이 시각(KST)에 수집→GitHub push. 비우면 비활성.
    auto_export_kst: str = ""  # 예: "07:30"
    auto_export_months: int = 12
    export_key: str = ""  # /admin/export 수동 트리거 키. 비우면 엔드포인트 비활성.

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allow_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.cache_dir.mkdir(parents=True, exist_ok=True)
    return s
