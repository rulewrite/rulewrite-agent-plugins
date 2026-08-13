#!/bin/bash
# gate-check.py 단위 테스트: 임시 git 저장소를 만들어 시나리오별 deny/통과를 검증한다.
set -u

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
GATE="$SCRIPT_DIR/../hooks/gate-check.py"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
PASS=0
FAIL=0

run_gate() { # $1=command $2=cwd → stdout 캡처
  python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":sys.argv[1]},"cwd":sys.argv[2]}))' "$1" "$2" | "$GATE"
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

git_t() { git -C "$REPO" -c user.email=t@t -c user.name=t "$@"; }

# ── 저장소 준비: 초기 커밋 + a.txt 스테이징 ──
REPO="$WORK/repo"
git init -q "$REPO"
git_t commit -q --allow-empty -m init
echo one >"$REPO/a.txt"
git_t add a.txt

# 1. 커밋 아닌 명령은 관여하지 않음
assert_pass "논커밋 명령" "$(run_gate 'ls -la' "$REPO")"

# 2. 인용부호 안의 git commit은 커밋이 아님
assert_pass "인용부 문자열" "$(run_gate 'echo "git commit -am x"' "$REPO")"

# 3. 마커 없이 커밋 → 퀴즈 안내와 함께 차단
assert_deny "마커 없는 커밋" "$(run_gate 'git commit -m "x"' "$REPO")" "comprehension-gate"

# 4. 글로벌 -c 옵션이 껴도 커밋으로 감지
assert_deny "글로벌 -c 옵션" "$(run_gate 'git -c user.name=x commit -m "y"' "$REPO")" "comprehension-gate"

# 5. 마커 일치 → 통과 (마커는 수동 기록; record-pass.sh는 Task 2에서 검증)
git -C "$REPO" write-tree >"$REPO/.git/comprehension-gate-pass"
assert_pass "마커 일치" "$(run_gate 'git commit -m "x"' "$REPO")"

# 6. heredoc 메시지 커밋도 마커 일치면 통과
HEREDOC_CMD='git commit -m "$(cat <<'"'"'EOF'"'"'
feat: 제목

본문
EOF
)"'
assert_pass "heredoc 메시지" "$(run_gate "$HEREDOC_CMD" "$REPO")"

# 7. 스테이징을 바꾸는 명령과 섞인 커밋은 마커와 무관하게 차단
assert_deny "add 체인" "$(run_gate 'git add a.txt && git commit -m "x"' "$REPO")" "한 명령줄에"

# 8. 스테이징이 바뀌면 재차단
echo two >>"$REPO/a.txt"
git_t add a.txt
assert_deny "스테이징 변경 후" "$(run_gate 'git commit -m "x"' "$REPO")" "comprehension-gate"

# 9. 스테이징 우회 옵션은 마커와 무관하게 차단
git -C "$REPO" write-tree >"$REPO/.git/comprehension-gate-pass"
assert_deny "-a 커밋" "$(run_gate 'git commit -am "x"' "$REPO")" "스테이징을 거치지 않는"
assert_deny "-all 커밋" "$(run_gate 'git commit --all -m "x"' "$REPO")" "스테이징을 거치지 않는"
assert_deny "pathspec 커밋" "$(run_gate 'git commit -m "x" a.txt' "$REPO")" "스테이징을 거치지 않는"
assert_deny "--fixup 미해석 옵션" "$(run_gate 'git commit --fixup HEAD' "$REPO")" "해석하지 못하는"
assert_pass "-m 결합형" "$(run_gate 'git commit -m"x"' "$REPO")"
assert_pass "리다이렉션 후행" "$(run_gate 'git commit -m "x" 2>&1' "$REPO")"
assert_pass "리다이렉션+파이프 후행" "$(run_gate 'git commit -m "x" 2>&1 | tail -5' "$REPO")"
assert_pass "출력 리다이렉션" "$(run_gate 'git commit -m "x" >/tmp/out.log' "$REPO")"
assert_deny "pathspec + 리다이렉션" "$(run_gate 'git commit -m "x" a.txt 2>&1' "$REPO")" "스테이징을 거치지 않는"

# 10. cd 프리픽스·-C는 해석해서 그 경로의 저장소 기준으로 검사 (워크트리 워크플로우)
REPO2="$WORK/repo2"
git init -q "$REPO2"
git -C "$REPO2" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
echo r2 >"$REPO2/z.txt"
git -C "$REPO2" add z.txt
assert_deny "cd 프리픽스, 마커 없음" "$(run_gate "cd $REPO2 && git commit -m \"x\"" "$WORK")" "이해 확인 전"
git -C "$REPO2" write-tree >"$REPO2/.git/comprehension-gate-pass"
assert_pass "cd 프리픽스, 마커 일치" "$(run_gate "cd $REPO2 && git commit -m \"x\"" "$WORK")"
assert_pass "git -C, 마커 일치" "$(run_gate "git -C $REPO2 commit -m \"x\"" "$WORK")"
assert_deny "복수 cd" "$(run_gate "cd $WORK && cd repo2 && git commit -m \"x\"" "$WORK")" "특정할 수 없는"
assert_deny "변수 경로" "$(run_gate 'cd $TARGET && git commit -m "x"' "$WORK")" "특정할 수 없는"
assert_pass "존재하지 않는 경로(&&)" "$(run_gate 'cd /no/such/dir && git commit -m "x"' "$WORK")"
assert_deny "세미콜론 구분 cd" "$(run_gate "cd $REPO2; git commit -m \"x\"" "$WORK")" "특정할 수 없는"

# 11. 빈 스테이징(메시지 amend 등)은 통과
rm -f "$REPO/.git/comprehension-gate-pass"
git_t commit -qm "staged 소진"
assert_pass "빈 스테이징" "$(run_gate 'git commit --amend --no-edit' "$REPO")"

# 12. 머지 종결 커밋은 통과 (Claude가 만든 변경이 아님)
git_t branch side
echo main-line >"$REPO/b.txt"
git_t add b.txt && git_t commit -qm main-side
git_t checkout -q side
echo side-line >"$REPO/c.txt"
git_t add c.txt && git_t commit -qm side-side
git_t checkout -q -
git_t merge --no-ff --no-commit side >/dev/null 2>&1
assert_pass "머지 진행 중" "$(run_gate 'git commit -m "merge"' "$REPO")"
git_t merge --abort

# 13. cherry-pick·revert 진행 중 커밋은 범위 밖 (Git이 대신 만드는 커밋)
rm -f "$REPO2/.git/comprehension-gate-pass"
git -C "$REPO2" rev-parse HEAD >"$REPO2/.git/CHERRY_PICK_HEAD"
assert_pass "cherry-pick 진행 중" "$(run_gate 'git commit -m "x"' "$REPO2")"
rm "$REPO2/.git/CHERRY_PICK_HEAD"
git -C "$REPO2" rev-parse HEAD >"$REPO2/.git/REVERT_HEAD"
assert_pass "revert 진행 중" "$(run_gate 'git commit -m "x"' "$REPO2")"
rm "$REPO2/.git/REVERT_HEAD"

# 14. record-pass.sh 라운드트립: 기록 → 게이트 통과
RECORD="$SCRIPT_DIR/../scripts/record-pass.sh"
echo three >"$REPO/d.txt"
git_t add d.txt
assert_deny "기록 전 차단" "$(run_gate 'git commit -m "x"' "$REPO")" "comprehension-gate"
(cd "$REPO" && "$RECORD" >/dev/null)
assert_pass "기록 후 통과" "$(run_gate 'git commit -m "x"' "$REPO")"

echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
