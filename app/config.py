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

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allow_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.cache_dir.mkdir(parents=True, exist_ok=True)
    return s
