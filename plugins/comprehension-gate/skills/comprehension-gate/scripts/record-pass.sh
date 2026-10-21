#!/bin/bash
# 퀴즈 통과 시에만 실행: 현재 인덱스 트리 해시를 마커로 기록해 게이트를 연다.
set -euo pipefail

git_dir=$(git rev-parse --git-dir)
tree=$(git write-tree)
printf '%s\n' "$tree" >"$git_dir/comprehension-gate-pass"
echo "comprehension-gate: 이해 확인 기록 완료 ($tree)"
