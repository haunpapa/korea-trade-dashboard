FROM python:3.12-slim

WORKDIR /srv

# 의존성 레이어 (캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY korea-trade-sector-dashboard.html .

# 비루트 실행
RUN useradd -m runner && mkdir -p /srv/_cache && chown -R runner:runner /srv
USER runner

ENV CACHE_DIR=/srv/_cache
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\",8000)}/health')" || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
