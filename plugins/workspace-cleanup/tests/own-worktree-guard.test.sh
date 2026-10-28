#!/bin/bash
# own-worktree-guard.py 단위 테스트: 임시 저장소와 워크트리를 만들어 시나리오별 deny/통과를 검증한다.
set -u

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
GUARD="$SCRIPT_DIR/../hooks/own-worktree-guard.py"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
PASS=0
FAIL=0

run_guard() { # $1=command $2=cwd → stdout 캡처 (환경변수는 호출부에서 앞에 붙인다)
  python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":sys.argv[1]},"cwd":sys.argv[2]}))' "$1" "$2" | "$GUARD"
}

run_guard_raw() { # $1=stdin JSON 원문
  printf '%s' "$1" | "$GUARD"
}

assert_pass() { # $1=라벨 $2=출력
  if [ -z "$2" ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); echo "FAIL(통과 기대): $1 → $2"; fi
}

assert_deny() { # $1=라벨 $2=출력 $3=사유에 포함될 문자열
  if grep -q '"permissionDecision": "deny"' <<<"$2" && grep -q "$3" <<<"$2"; then
    PASS=$((PASS+1))
  else
    FAIL=$((FAIL+1)); echo "FAIL(차단 기대): $1 → ${2:-<출력 없음>}"
  fi
}

SELF="이거나 그 상위"
UNRESOLVED="판정할 수 없어"

# ── 저장소 준비: main 체크아웃 + 워크트리 wt·wt2, wt 안에 하위 디렉터리 ──
MAIN="$WORK/main"
WT="$WORK/wt"
WT2="$WORK/wt2"
git init -q "$MAIN"
git -C "$MAIN" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
git -C "$MAIN" worktree add -q "$WT"
git -C "$MAIN" worktree add -q "$WT2"
mkdir -p "$WT/projects/gift/dist" "$WT/node_modules"
ln -s wt "$WORK/link"

# 0. 훅 파일은 실행 가능해야 한다 (hooks.json이 직접 실행)
if [ -x "$GUARD" ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); echo "FAIL: 훅에 실행 비트 없음"; fi

# ── 자기 발밑: 차단 ──
assert_deny "절대경로 remove" "$(run_guard "git worktree remove $WT" "$WT")" "$SELF"
assert_deny "remove ." "$(run_guard 'git worktree remove .' "$WT")" "$SELF"
assert_deny "메인에서 -C로 자기 제거" "$(run_guard "git -C $MAIN worktree remove $WT" "$WT")" "$SELF"
INCIDENT="MAIN=\$(git worktree list | head -1 | awk '{print \$1}'); echo \$MAIN; git -C \"\$MAIN\" worktree remove $WT && git -C \"\$MAIN\" branch -D feat/x && git -C \"\$MAIN\" worktree list | grep -c x"
assert_deny "사고 명령 원형(-C 변수 + 절대경로)" "$(run_guard "$INCIDENT" "$WT")" "$SELF"
assert_deny "cd 뒤 상대경로" "$(run_guard "cd $MAIN && git worktree remove ../wt" "$WT")" "$SELF"
assert_deny "--force --force --" "$(run_guard "git worktree remove --force --force -- $WT" "$WT")" "$SELF"
assert_deny "-ff 상대경로" "$(run_guard 'git worktree remove -ff ../wt' "$WT")" "$SELF"
assert_deny "rm -rf 절대경로" "$(run_guard "rm -rf $WT" "$WT")" "$SELF"
assert_deny "rm -Rf" "$(run_guard "rm -Rf $WT" "$WT")" "$SELF"
assert_deny "rm -r -f --" "$(run_guard "rm -r -f -- $WT" "$WT")" "$SELF"
assert_deny "rm --recursive" "$(run_guard "rm --recursive --force $WT" "$WT")" "$SELF"
assert_deny "/bin/rm" "$(run_guard "/bin/rm -rf $WT" "$WT")" "$SELF"
assert_deny "sudo rm" "$(run_guard "sudo rm -rf $WT" "$WT")" "$SELF"
assert_deny "하위 디렉터리에 서 있을 때 그 디렉터리" "$(run_guard "rm -rf $WT/projects/gift" "$WT/projects/gift")" "$SELF"
assert_deny "하위 디렉터리에서 워크트리 루트" "$(run_guard "git worktree remove $WT" "$WT/projects/gift")" "$SELF"
assert_deny "rm -rf .." "$(run_guard 'rm -rf ..' "$WT/projects/gift")" "$SELF"
assert_deny "worktree move 자기" "$(run_guard 'git worktree move . ../wt-old' "$WT")" "$SELF"
assert_deny "mv 자기" "$(run_guard "mv $WT $WORK/x" "$WT")" "$SELF"
assert_deny "mv -t" "$(run_guard "mv -t $WORK $WT" "$WT")" "$SELF"
assert_deny "trash 자기" "$(run_guard "trash $WT" "$WT")" "$SELF"
assert_deny "rmdir 자기" "$(run_guard "rmdir $WT" "$WT")" "$SELF"
assert_deny "체인 뒤쪽" "$(run_guard "git fetch -q && git worktree remove $WT2; rm -rf $WT" "$WT")" "$SELF"
assert_deny "프로젝트 디렉터리(CLAUDE_PROJECT_DIR)" "$(CLAUDE_PROJECT_DIR="$MAIN" run_guard "rm -rf $MAIN" "$WT")" "$SELF"
assert_deny "~ 확장" "$(HOME="$WORK" run_guard 'rm -rf ~/wt' "$WT")" "$SELF"
assert_deny "심링크 + 후행 슬래시" "$(run_guard "git worktree remove $WORK/link/" "$WT")" "$SELF"
assert_deny "realpath 형태 vs 심링크 cwd" "$(run_guard "rm -rf $(realpath "$WT")" "$WT")" "$SELF"
assert_deny "cwd 없는 입력은 CLAUDE_PROJECT_DIR로 판정" "$(CLAUDE_PROJECT_DIR="$WT" run_guard_raw '{"tool_name":"Bash","tool_input":{"command":"rm -rf '"$WT"'"}}')" "$SELF"
if [ -e "$WORK/WT" ]; then # 대소문자 무시 파일시스템(macOS APFS)에서만 의미 있는 케이스
  assert_deny "대소문자만 다른 경로" "$(run_guard "rm -rf $WORK/WT" "$WT")" "$SELF"
fi

# ── 해석 불가: 차단하되 사유가 다르다 ──
assert_deny "변수 단독" "$(run_guard 'rm -rf "$W"' "$WT")" "$UNRESOLVED"
assert_deny "변수 remove" "$(run_guard "W=$WT2; git worktree remove \$W" "$WT")" "$UNRESOLVED"
assert_deny "상위 접두 + 명령 치환" "$(run_guard 'rm -rf ../$(basename "$PWD")' "$WT")" "$UNRESOLVED"
assert_deny "cd 변수 뒤 상대경로" "$(run_guard 'cd $D && rm -rf wt' "$WT")" "$UNRESOLVED"
assert_deny "훅 내부 오류는 차단" "$(run_guard_raw '{"tool_name":"Bash","tool_input":{"command":"rm -rf '"$WT"'"},"cwd":123}')" "내부 오류"


# ── 2차 검토: 예약어·래퍼 뒤 동사, 이름 일부 글롭, 동적 토큰 뒤 .., cd 추적, rm -d ──
assert_deny "if/then 관용구" "$(run_guard "if [ -d $WT ]; then git worktree remove $WT; fi" "$WT")" "$SELF"
assert_deny "중괄호 그룹" "$(run_guard "{ rm -rf $WT; }" "$WT")" "$SELF"
assert_deny "timeout 래퍼" "$(run_guard "timeout 5 rm -rf $WT" "$WT")" "$SELF"
assert_deny "sudo -u 래퍼" "$(run_guard "sudo -u me rm -rf $WT" "$WT")" "$SELF"
assert_deny "이름 일부 글롭(상대)" "$(run_guard 'rm -rf ../w*' "$WT")" "$UNRESOLVED"
assert_deny "이름 일부 글롭(절대)" "$(run_guard "rm -rf $WORK/w?" "$WT")" "$UNRESOLVED"
assert_deny "브레이스 확장" "$(run_guard "rm -rf $WORK/{wt,wt2}" "$WT")" "$UNRESOLVED"
assert_deny "동적 토큰 뒤 .." "$(run_guard 'rm -rf dist/$X/../../..' "$WT/projects/gift")" "$UNRESOLVED"
assert_deny "존재하지 않는 cd 뒤 ." "$(run_guard 'cd /no/such/dir; rm -rf .' "$WT")" "$UNRESOLVED"
assert_deny "cd - 뒤 ." "$(run_guard "cd $MAIN && cd - && rm -rf ." "$WT")" "$UNRESOLVED"
assert_deny "-C 두 번 순차 적용" "$(run_guard 'git -C .. -C wt worktree remove .' "$WT")" "$SELF"
assert_deny "rm -d" "$(run_guard "rm -d $WT" "$WT")" "$SELF"
assert_deny "토큰화 실패 + 리터럴 자기 경로" "$(run_guard "echo it's; rm -rf $WT" "$WT")" "$SELF"
SELF_OUT=$(run_guard 'git worktree remove .' "$WT")
if grep -q "(= $(realpath "$WT"))" <<<"$SELF_OUT"; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); echo "FAIL: 사유에 절대경로 없음 → $SELF_OUT"; fi


# ── PR 리뷰: 이름만으로 remove, $() 분리, heredoc 줄 잔여, 예약어 뒤 cd, 서브셸 cd, find 시작점, 첫 cwd 기억 ──
assert_deny "[1] 디렉터리 이름만으로 remove(-C)" "$(run_guard "git -C $MAIN worktree remove wt" "$WT")" "$SELF"
assert_deny "[1] 디렉터리 이름만으로 remove(cd)" "$(run_guard "cd $MAIN && git worktree remove wt" "$WT")" "$SELF"
assert_deny "[2] -C \$() 뒤 절대경로" "$(run_guard "git -C \$(git rev-parse --show-toplevel) worktree remove $WT" "$WT")" "$SELF"
assert_deny "[2] 백틱 뒤 절대경로" "$(run_guard "git -C \`git rev-parse --show-toplevel\` worktree remove $WT" "$WT")" "$SELF"
assert_deny "[3] heredoc 줄의 ; 체인" "$(run_guard "cat <<'EOF' > handover.md; git -C $MAIN worktree remove $WT
hello
EOF" "$WT")" "$SELF"
assert_deny "[4] then 뒤 cd" "$(run_guard 'if true; then cd ..; rm -rf wt; fi' "$WT")" "$SELF"
assert_deny "[4] 중괄호 뒤 cd" "$(run_guard '{ cd ..; rm -rf wt; }' "$WT")" "$SELF"
assert_deny "[4] builtin cd" "$(run_guard 'builtin cd .. && rm -rf wt' "$WT")" "$SELF"
assert_deny "[5] 서브셸 cd는 바깥에 안 샘" "$(run_guard '(cd /tmp); rm -rf ../wt' "$WT")" "$SELF"
assert_deny "[5] 인자 없는 pushd 뒤 상대경로" "$(run_guard "pushd $MAIN; pushd; rm -rf ." "$WT")" "$UNRESOLVED"
assert_deny "[6] find 시작점이 자기 루트" "$(run_guard "find $WT -exec rm -rf {} +" "$WT")" "$SELF"
assert_deny "[6] find . -delete" "$(run_guard 'find . -name x -delete' "$WT")" "$SELF"
DATA="$WORK/plugin-data"
CLAUDE_PLUGIN_DATA="$DATA" run_guard_raw '{"session_id":"s1","tool_name":"Bash","tool_input":{"command":"ls"},"cwd":"'"$WT"'"}' >/dev/null
assert_deny "[7] 첫 호출 cwd를 기억해 cd로 빠져나간 뒤 삭제도 차단" "$(CLAUDE_PLUGIN_DATA="$DATA" run_guard_raw '{"session_id":"s1","tool_name":"Bash","tool_input":{"command":"git worktree remove '"$WT"'"},"cwd":"'"$MAIN"'"}')" "$SELF"
assert_pass "[7] 다른 세션 id는 영향 없음" "$(CLAUDE_PLUGIN_DATA="$DATA" run_guard_raw '{"session_id":"s2","tool_name":"Bash","tool_input":{"command":"git worktree remove '"$WT"'"},"cwd":"'"$MAIN"'"}')"
if grep -q '"onFailure": "block"' "$SCRIPT_DIR/../hooks/hooks.json"; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); echo "FAIL: [8] hooks.json에 onFailure block 없음"; fi
RM_OUT=$(run_guard 'rm -rf ..' "$WT/projects/gift")
if grep -q "worktree remove" <<<"$RM_OUT"; then FAIL=$((FAIL+1)); echo "FAIL: [9] rm 차단 사유에 worktree remove 예시가 붙음 → $RM_OUT"; else PASS=$((PASS+1)); fi
WT_OUT=$(run_guard 'git worktree remove .' "$WT")
if grep -q "worktree remove $(realpath "$WT")" <<<"$WT_OUT"; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); echo "FAIL: [9] worktree remove 차단 사유에 절대경로 예시 없음 → $WT_OUT"; fi

# ── 통과 ──
assert_pass "무관한 명령" "$(run_guard 'ls -la' "$WT")"
assert_pass "인용부 문자열" "$(run_guard "echo \"rm -rf $WT\"" "$WT")"
assert_pass "node_modules" "$(run_guard 'rm -rf node_modules' "$WT")"
assert_pass "와일드카드 하위" "$(run_guard 'rm -rf dist/*' "$WT/projects/gift")"
assert_pass "하위 절대경로" "$(run_guard "rm -rf $WT/projects/gift/dist" "$WT")"
assert_pass "비재귀 rm" "$(run_guard "rm $WT" "$WT")"
assert_pass "형제 워크트리 제거" "$(run_guard "git worktree remove $WT2" "$WT")"
assert_pass "prune" "$(run_guard 'git worktree prune' "$WT")"
assert_pass "cd 메인 뒤 형제 제거" "$(run_guard "cd $MAIN && git worktree remove $WT2" "$WT")"
assert_pass "-C 상대경로는 -C 기준" "$(run_guard "git -C $MAIN worktree remove ../wt2" "$WT")"
assert_pass "무관한 접두 + 변수" "$(run_guard "rm -rf $WORK/scratch/\$ID" "$WT")"
assert_pass "메인 세션의 워크트리 제거(인수인계 명령)" "$(run_guard "git worktree remove $WT" "$MAIN")"
assert_pass "mv 하위" "$(run_guard "mv $WT/projects/gift/dist $WT/projects/old" "$WT")"
assert_pass "내부 오류라도 위험 동사 없으면 통과" "$(run_guard_raw '{"tool_name":"Bash","tool_input":{"command":"ls"},"cwd":123}')"
assert_pass "heredoc 본문의 인수인계 명령" "$(run_guard "cat <<'EOF' > handover.md
git -C $MAIN worktree remove $WT
EOF" "$WT")"
assert_pass "토큰화 실패 + 무관한 삭제" "$(run_guard "echo it's; rm -rf node_modules" "$WT")"
assert_pass "find 시작점이 하위 디렉터리면 -exec rm 통과" "$(run_guard 'find dist -name "*.map" -exec rm -rf {} +' "$WT/projects/gift")"
assert_pass "글롭 접두가 하위 디렉터리" "$(run_guard 'rm -rf projects/gift/dist/*' "$WT")"
assert_pass "변수 앞 무관한 절대 디렉터리" "$(run_guard "rm -rf $WORK/scratch/x-\$ID" "$WT")"
assert_pass "[1] 이름만으로 형제 워크트리 remove" "$(run_guard "git -C $MAIN worktree remove wt2" "$WT")"
assert_pass "[2] \$() 안의 무관한 명령" "$(run_guard "echo \$(git -C $MAIN worktree list | wc -l)" "$WT")"
assert_pass "[3] heredoc 본문만 쓰는 인수인계 파일" "$(run_guard "cat <<'EOF' > handover.md
git -C $MAIN worktree remove $WT
EOF
echo done" "$WT")"

echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
