#!/bin/bash
# 사용법: notify.sh <본문> <소리 이름>
# 제목은 프로젝트 이름. 여러 세션을 띄워도 어느 작업의 알림인지 구분되게 한다.
root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)

# 일부 에이전트(Codex의 Stop 등)는 stdout을 결과로 해석하므로 아무것도 출력하지 않는다.
osascript - "$1" "$(basename "$root")" "$2" >/dev/null 2>&1 <<'EOF'
on run argv
  display notification (item 1 of argv) with title (item 2 of argv) sound name (item 3 of argv)
end run
EOF
exit 0
