#!/usr/bin/env bash
# ───────────────────────────────────────────────────────────────
#  관세청 월간 HS 통계 수집 → data/*.json 재생성 → git push  (macOS / Linux)
#  update-data.bat 의 Mac 판. data.go.kr 은 해외 IP 를 차단하므로 한국 IP 에서 실행.
#
#  사용법
#    ./update-data.sh                 # 수집 + data/ 커밋·푸시
#    ./update-data.sh --no-push       # 수집만 (로컬 data/ 갱신)
#    ./update-data.sh --months 6      # export_static.py 인자 그대로 전달
#
#  준비
#    .env 에 CUSTOMS_SERVICE_KEY=... (data.go.kr 인증키)
#    git remote 에 push 권한 (gh auth login 또는 SSH 키)
#  로그: logs/update-data.log
# ───────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
mkdir -p logs
LOG="logs/update-data.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== $(date '+%F %T') update-data.sh 시작 ==="

PUSH=1
ARGS=()
for a in "$@"; do
  case "$a" in
    --no-push) PUSH=0 ;;
    *) ARGS+=("$a") ;;
  esac
done

# .env 로드 (값은 출력하지 않음)
if [[ -f .env ]]; then
  set -a; # shellcheck disable=SC1091
  source .env; set +a
fi
if [[ -z "${CUSTOMS_SERVICE_KEY:-}" ]]; then
  echo "오류: CUSTOMS_SERVICE_KEY 가 없습니다. .env 에 추가하세요." >&2
  exit 2
fi

# venv 부트스트랩
if [[ ! -x .venv/bin/python ]]; then
  echo "venv 생성 중…"
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
PY=.venv/bin/python

# 수집 (캐시 _cache/ 는 로컬에 남아 다음 실행은 신규 월만 호출)
"$PY" scripts/export_static.py ${ARGS[@]+"${ARGS[@]}"}

if [[ "$PUSH" -eq 0 ]]; then
  echo "완료 (--no-push): data/ 로컬 갱신만"
  exit 0
fi

# git 으로 푸시 (GITHUB_TOKEN 불필요 — 로컬 git 자격증명 사용)
if git diff --quiet -- data/; then
  echo "변경 없음 — 푸시 생략"
  exit 0
fi
END_YYMM="$("$PY" -c 'import json;print(json.load(open("data/meta.json"))["end_yymm"])' 2>/dev/null || echo '?')"
git add data/
git -c user.name="${GIT_AUTHOR_NAME:-update-data}" -c user.email="${GIT_AUTHOR_EMAIL:-update-data@local}" \
  commit -q -m "data: 월간 HS 통계 갱신 (end=${END_YYMM}, update-data.sh)"
git push -q origin HEAD
echo "푸시 완료 — 대시보드가 다음 로드부터 새 데이터를 사용합니다 (end=${END_YYMM})."
