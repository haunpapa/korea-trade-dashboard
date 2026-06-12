"""하위호환 진입점 — `uvicorn main:app`도 계속 동작합니다.

실제 구현은 app/ 패키지로 이동했습니다. 신규 명령: uvicorn app.main:app
"""

from app.main import app

__all__ = ["app"]
