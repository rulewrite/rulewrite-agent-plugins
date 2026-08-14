#!/bin/bash
# pick-answer-slots.sh 단위 테스트: 정답 자리가 매번 새로 뽑히고 한쪽으로 몰리지 않는지 검증한다.
set -u

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PICK="$SCRIPT_DIR/../scripts/pick-answer-slots.sh"
PASS=0
FAIL=0

ok() { # $1=라벨 $2=조건 결과(0=성공)
  if [ "$2" -eq 0 ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); echo "FAIL: $1"; fi
}

# 1. 문항 수만큼 자리를 낸다
count=$("$PICK" 4 4 4 4 | wc -w | tr -d ' ')
ok "4문항 → 자리 4개 (실제 $count)" "$([ "$count" = 4 ] && echo 0 || echo 1)"

# 2. 보기 범위를 벗어나거나 인접 문항이 같은 자리를 쓰지 않는다
violations=$(for _ in $(seq 300); do "$PICK" 4 4 4 4; done | awk '
  {for (i = 1; i <= NF; i++) {
     if ($i < 1 || $i > 4) bad++
     if (i > 1 && $i == $(i-1)) bad++
   }}
  END {print bad+0}')
ok "범위 밖·인접 중복 없음 (위반 $violations)" "$([ "$violations" = 0 ] && echo 0 || echo 1)"

# 3. 한 자리에 절반 넘게 몰리지 않는다 (4문항이면 같은 자리 최대 2회)
crowded=$(for _ in $(seq 300); do "$PICK" 4 4 4 4; done | awk '
  {delete seen; over = 0
   for (i = 1; i <= NF; i++) {seen[$i]++; if (seen[$i] > 2) over = 1}
   if (over) n++}
  END {print n+0}')
ok "한 자리 3회 이상 몰림 없음 (발생 $crowded)" "$([ "$crowded" = 0 ] && echo 0 || echo 1)"

# 4. 매 실행 새로 뽑는다 — 고정 배열이면 위치를 학습당해 게이트가 무력해진다
distinct=$(for _ in $(seq 50); do "$PICK" 4 4 4 4; done | sort -u | wc -l | tr -d ' ')
ok "50회 중 서로 다른 배열 다수 (실제 $distinct)" "$([ "$distinct" -ge 10 ] && echo 0 || echo 1)"

# 5. 첫 문항 정답이 특정 자리에 치우치지 않는다 (400회면 자리당 100 안팎)
skew=$(for _ in $(seq 400); do "$PICK" 4 4 4 4; done | awk '
  {seen[$1]++}
  END {for (slot = 1; slot <= 4; slot++) if (seen[slot] < 60 || seen[slot] > 140) n++; print n+0}')
ok "첫 문항 자리 분포 균등 (치우친 자리 $skew)" "$([ "$skew" = 0 ] && echo 0 || echo 1)"

# 6. 보기 수가 문항마다 달라도 각자의 범위를 지킨다
mixed_bad=$(for _ in $(seq 200); do "$PICK" 2 3 4; done | awk '
  {if ($1 > 2 || $2 > 3 || $3 > 4) n++}
  END {print n+0}')
ok "문항별 보기 수 반영 (위반 $mixed_bad)" "$([ "$mixed_bad" = 0 ] && echo 0 || echo 1)"

# 7. 제약이 빡빡한 조합에서도 멈추지 않고 끝난다
"$PICK" 2 2 2 2 2 2 >/dev/null 2>&1 &
pick_pid=$!
{ sleep 5; kill -9 $pick_pid; } 2>/dev/null &
watchdog_pid=$!
wait $pick_pid 2>/dev/null
ok "2지선다 6문항도 완주" "$?"
kill $watchdog_pid 2>/dev/null
wait $watchdog_pid 2>/dev/null

# 8. 잘못된 인자는 거부한다
"$PICK" >/dev/null 2>&1
ok "인자 없음 거부" "$([ $? -ne 0 ] && echo 0 || echo 1)"
"$PICK" 4 1 >/dev/null 2>&1
ok "보기 수 1 거부" "$([ $? -ne 0 ] && echo 0 || echo 1)"

echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
