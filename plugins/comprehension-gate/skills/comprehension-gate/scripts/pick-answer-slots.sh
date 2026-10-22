#!/bin/bash
# 문항을 쓰기 전에 정답이 놓일 자리를 뽑는다.
# 출제자(모델)는 자기가 옳다고 믿는 보기를 앞에 두려는 편향이 있어, 위치 선택을 밖으로 빼낸다.
set -eu

if [ $# -eq 0 ]; then
  echo "usage: $(basename "$0") <문항1 보기수> [문항2 보기수 ...]" >&2
  exit 1
fi

# 한 자리에 정답이 절반 넘게 몰리지 않게 한다. 문항이 적을수록 빡빡해진다.
max_per_slot=$(( ($# + 1) / 2 ))
used=(0 0 0 0 0 0 0 0 0 0)
slots=""
prev=0

for option_count in "$@"; do
  case $option_count in
    [2-9]) ;;
    *) echo "보기 수는 2~9 사이여야 합니다: $option_count" >&2; exit 1 ;;
  esac

  attempt=0
  while :; do
    pick=$(( RANDOM % option_count + 1 ))
    attempt=$(( attempt + 1 ))
    # 제약이 서로 막아 뽑을 자리가 없는 조합에서 멈추지 않도록, 오래 헤매면 직전 반복 회피만 남긴다.
    if [ "$attempt" -ge 200 ]; then
      [ "$pick" != "$prev" ] && break
      continue
    fi
    [ "$pick" = "$prev" ] && continue
    [ "${used[$pick]}" -ge "$max_per_slot" ] && continue
    break
  done

  used[$pick]=$(( used[pick] + 1 ))
  slots="$slots $pick"
  prev=$pick
done

echo "${slots# }"
