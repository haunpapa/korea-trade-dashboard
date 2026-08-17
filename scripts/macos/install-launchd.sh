#!/usr/bin/env bash
# launchd 에이전트 설치/제거 — 매일 09:00 update-data.sh 자동 실행
#   ./scripts/macos/install-launchd.sh            # 설치(또는 재설치)
#   ./scripts/macos/install-launchd.sh --uninstall
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LABEL="com.haunpapa.korea-trade-update"
DST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ "${1:-}" == "--uninstall" ]]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$DST"; echo "제거 완료: $LABEL"; exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/logs"
sed "s#__REPO__#$ROOT#g" "$ROOT/scripts/macos/$LABEL.plist" > "$DST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$DST"
launchctl print "gui/$(id -u)/$LABEL" | grep -E "state|last exit" | head -3
echo "설치 완료: 매일 09:00 실행. 지금 바로 한 번 돌리려면: launchctl kickstart -k gui/$(id -u)/$LABEL"
