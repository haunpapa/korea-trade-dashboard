# 관세청 → 수출입동향 섹터 대시보드

`korea-trade-sector-dashboard.html`(단일 파일 대시보드)을 관세청 무역통계 Open API로 자동 채우는 FastAPI 서비스입니다.

> **데이터원**: 공공데이터포털 *관세청_품목별 국가별 수출입실적* (`getNitemtradeList`).
> HS코드 기준 **월간 확정** 통계 — 매월 15일경 전월 데이터가 현행화됩니다.

---

## 1. 프로젝트 구조

```
Korea/
├── app/                  # FastAPI 서비스
│   ├── main.py           #   라우트 + 대시보드 서빙(/)
│   ├── config.py         #   설정 (.env, pydantic-settings)
│   ├── customs.py        #   관세청 API 클라이언트 (재시도·페이지네이션)
│   ├── aggregate.py      #   집계 로직 (총괄·섹터·권역·추세)
│   ├── mappings.py       #   HS↔품목, 국가↔권역 매핑
│   └── cache.py          #   파일 영구 캐시
├── tests/                # pytest (네트워크 불필요, mock 기반)
├── korea-trade-sector-dashboard.html
├── main.py               # 하위호환 진입점 (uvicorn main:app)
├── Dockerfile / railway.json / Procfile
└── .env.example          # → .env로 복사 후 키 입력
```

## 2. 빠른 시작

```bash
# (1) 의존성
pip install -r requirements.txt          # 운영
pip install -r requirements-dev.txt     # 개발(테스트·린트 포함)

# (2) 인증키 — .env 파일 사용 (export 불필요)
cp .env.example .env                     # Windows: copy .env.example .env
#    .env 열어 CUSTOMS_SERVICE_KEY에 'Decoding' 키 입력

# (3) 실행
uvicorn app.main:app --reload
```

**http://localhost:8000/** 을 열면 대시보드가 뜨고, 같은 출처라 **자동으로 API 연동**됩니다
(연동 성공 시 상단에 `⚡ API 실시간 연동` 배지 + 추세 차트에 권역 탭 표시).

확인:
```bash
curl "http://localhost:8000/health"
curl "http://localhost:8000/api/monthly?yymm=202605"
curl "http://localhost:8000/api/trend?months=12"
curl "http://localhost:8000/api/sector-trend?group=IT·반도체&months=12"
curl "http://localhost:8000/api/region-trend?region=중국&months=12"
```

### 응답 필드가 안 맞으면
```bash
curl "http://localhost:8000/debug/raw?yymm=202605&hs=85"
```
출력의 키 이름이 `expDlr/impDlr/balPayments/statKor/hsCd`와 다르면 `app/customs.py` 상단 `F_*` 상수만 고치면 됩니다.

## 3. API 엔드포인트

| 경로 | 설명 |
|---|---|
| `GET /` | 대시보드 HTML (같은 출처 자동 연동) |
| `GET /health` | 상태 + 캐시 통계 |
| `GET /api/monthly?yymm=` | 월간 총괄·품목·권역 (YoY 포함) |
| `GET /api/trend?months=&end=` | 총수출·수지 월별 시계열 |
| `GET /api/sectors?yymm=` | 품목별 수출액 |
| `GET /api/sector-trend?group=&months=` | 산업분야별 시계열 (5개 그룹) |
| `GET /api/region-trend?region=&months=` | 권역별 시계열 (9대 권역) |
| `GET /debug/raw?yymm=&hs=` | 원본 응답 점검용 |

공통: `?refresh=1`로 캐시 무시 강제 갱신.

## 4. 테스트·린트

```bash
pytest                # 35개 테스트, 네트워크 불필요
ruff check app tests
black app tests
```

## 5. 배포 (Railway)

1. 이 폴더를 GitHub repo로 푸시 (`.env`는 `.gitignore`로 제외됨)
2. Railway → New Project → Deploy from repo — `railway.json`이 Docker 빌드·헬스체크·시작 명령을 자동 적용
3. **Variables**에 `CUSTOMS_SERVICE_KEY` 등록
4. (선택) `ALLOW_ORIGINS=https://내도메인` 으로 CORS 제한

정적 호스팅(GitHub Pages)에 HTML만 따로 올리는 경우: HTML 하단 `API_BASE_OVERRIDE`에 배포된 서버 주소를 입력하세요.

Docker 직접 실행:
```bash
docker build -t korea-trade .
docker run -p 8000:8000 --env-file .env korea-trade
```

## 6. 캐시 & 비용

- 월간 통계는 확정 후 불변 → `_cache/`에 영구 캐시, `?refresh=1`로 갱신
- `/api/trend` 최초 호출은 chapter 01~99 × 12개월이라 다소 느림 (이후 캐시 즉시 응답)
- 개발계정 트래픽 10,000/일 — 캐시면 충분. 동시성은 `CONCURRENCY`(기본 8)로 조절
- **페이지네이션 지원** — `totalCount` 기준 전 페이지 수집으로 행 누락 방지

## 7. ⚠️ 섹터 매핑은 '근사치'입니다

산업부 **15대 품목은 MTI 분류**, 이 A