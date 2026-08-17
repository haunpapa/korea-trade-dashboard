#!/usr/bin/env bash
# launchd 에이전트 설치/제거 — 매일 09:00 update-data.sh 자동 실행
#
#   ./scripts/macos/install-launchd.sh                 # 설치(기본 작업 폴더 = ~/.local/share/korea-trade-dashboard)
#   ./scripts/macos/install-launchd.sh --repo DIR      # 작업 폴더 지정
#   ./scripts/macos/install-launchd.sh --uninstall
#
# 왜 작업 폴더를 따로 두나: macOS TCC 는 launchd 백그라운드 프로세스의 ~/Documents·Desktop·Downloads
# 접근을 차단한다("Operation not permitted"). 그래서 보호 폴더 밖에 전용 클론을 두고 거기서 수집·푸시한다.
# (대안: 시스템 설정 → 개인정보 보호 → 전체 디스크 접근에 /bin/bash 추가 후 --repo 로 이 레포 지정)
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LABEL="com.haunpapa.korea-trade-update"
DST="$HOME/Library/LaunchAgents/$LABEL.plist"
REPO="$HOME/.local/share/korea-trade-dashboard"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --uninstall)
      launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
      rm -f "$DST"; echo "제거 완료: $LABEL (작업 폴더는 남겨둠)"; exit 0 ;;
    --repo) REPO="$2"; shift 2 ;;
    *) echo "알 수 없는 옵션: $1" >&2; exit 2 ;;
  esac
done

case "$REPO" in
  "$HOME/Documents"*|"$HOME/Desktop"*|"$HOME/Downloads"*)
    echo "경고: $REPO 는 TCC 보호 폴더라 launchd 에서 접근이 막힐 수 있습니다(전체 디스크 접근 권한 없으면 실패)." >&2 ;;
esac

# 작업 폴더 준비: 없으면 origin 에서 클론, 있으면 최신화
if [[ ! -d "$REPO/.git" ]]; then
  ORIGIN="$(git -C "$SRC" remote get-url origin)"
  echo "작업 폴더 클론: $ORIGIN → $REPO"
  git clone -q "$ORIGIN" "$REPO"
else
  git -C "$REPO" pull -q --ff-only || echo "경고: $REPO pull 실패(로컬 변경?) — 계속 진행"
fi
# .env(서비스키) 는 git 밖 — 원본에 있고 작업 폴더에 없으면 복사
if [[ -f "$SRC/.env" && ! -f "$REPO/.env" ]]; then
  cp "$SRC/.env" "$REPO/.env"; chmod 600 "$REPO/.env"; echo ".env 복사 → $REPO/.env"
fi
[[ -f "$REPO/.env" ]] || echo "경고: $REPO/.env 가 없습니다. CUSTOMS_SERVICE_KEY 를 넣어야 수집이 됩니다." >&2

mkdir -p "$HOME/Library/LaunchAgents" "$REPO/logs"
sed "s#__REPO__#$REPO#g" "$SRC/scripts/macos/$LABEL.plist" > "$DST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$DST"
launchctl print "gui/$(id -u)/$LABEL" | grep -E "state|last exit" | head -2
echo "설치 완료: 매일 09:00 실행, 작업 폴더 $REPO, 로그 $REPO/logs/"
echo "지금 바로 한 번 돌리려면: launchctl kickstart -k gui/$(id -u)/$LABEL"
