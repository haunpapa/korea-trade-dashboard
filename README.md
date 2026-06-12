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

## 5. 데이터 갱신 — 서버 자동(권장) 또는 PC 수동

> (구버전 안내 수정) 과거 "data.go.kr 해외 IP 차단(403)" 전제는 더 이상 사실이 아닙니다 —
> 2026-06 확인 결과 Railway에서도 관세청 API 호출이 가능하며, 한도 초과 시 429만 발생합니다.

### ① 서버 자동 export (권장 — Railway가 매일 수집해 GitHub에 push)

Railway 환경변수 두 개만 설정하면 PC 없이 완전 자동화됩니다:

| 변수 | 값 | 설명 |
|---|---|---|
| `GITHUB_TOKEN` | `github_pat_...` | fine-grained, 이 레포 Contents: R/W |
| `AUTO_EXPORT_KST` | `07:30` | 매일 실행 시각(한국시간). 비우면 비활성 |
| `EXPORT_KEY` | 임의 문자열 | (선택) `/admin/export?key=...` 수동 트리거용 |

- 매 실행 전 **최근 2개월 캐시만 삭제** 후 재조회 → 확정치 현행화(매월 15일경) 반영, 과거 달은 캐시 재사용으로 API 호출 최소화
- 상태 확인: `GET /health`의 `export` 필드 (`next_run`/`last_ok`/`last_error`)
- 수동 실행: `GET|POST /admin/export?key=EXPORT_KEY` (백그라운드 실행, 202 즉시 반환)
- ⚠️ Railway가 이 레포 자동 배포 중이면 **Settings → Watch Paths**에 `data/**` 제외 패턴을 추가하세요
  (데이터 커밋마다 재배포·캐시 초기화 방지): `/**` + `!data/**` 또는 `!/data/**`

### ② PC 수동 export (백업 수단)

```bash
# 사전 1회: .env에 GITHUB_TOKEN 추가 (fine-grained, 이 레포 Contents: R/W만)
update-data.bat            # Windows 더블클릭
# 또는
python scripts/export_static.py --push
```

발표일은 매월 1일(월간)·11일·21일(순별), 월간 확정치 현행화는 15일경입니다.

### 대시보드 데이터 우선순위
① 같은 출처 API(한국 IP에서 백엔드 실행 시 실시간) → ② GitHub 정적 JSON → ③ 내장 데이터.
배지로 현재 출처가 표시됩니다(`⚡ API 실시간` / `🗂 GitHub 데이터 · 날짜`).

## 6. 배포 (Railway — 대시보드 호스팅용)

현재 배포: