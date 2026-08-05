# comprehension-gate

Claude가 만든 변경을 사용자가 이해했다고 증명(literate diff 설명 + 퀴즈 통과)하기 전까지 `git commit`을 차단하는 인지적 부채 속도 조절기. Geoffrey Litt의 [Understanding is the new bottleneck](https://www.geoffreylitt.com/2026/07/02/understanding-is-the-new-bottleneck.html)에서 착안.

## 동작

1. PreToolUse hook이 Claude의 `git commit`을 가로채, 퀴즈 통과 기록(인덱스 트리 해시)이 현재 스테이징과 일치할 때만 통과시킨다.
2. 차단되면 Claude가 스킬을 따라 배경→직관→워크스루 순서의 설명과 이해도 퀴즈를 진행한다.
3. 퀴즈를 통과하면 기록이 남고 커밋이 통과된다. 스테이징이 바뀌면 기록이 무효화되어 다시 걸린다.

게이트 생략이 필요하면 대화에서 직접 지시한다 (예: "이 커밋은 게이트 생략해").

## 범위 밖 (의도된 설계)

- 사용자가 터미널에서 직접 하는 커밋, `git push`, PR 생성은 막지 않는다.
- merge·cherry-pick·revert 등 Git이 대신 만드는 커밋은 게이트 대상이 아니다.

## 한계

- Claude가 통과 기록 스크립트를 임의 실행하는 우회를 물리적으로 차단할 수는 없다 (스킬 지침으로 금지).
- Claude Code의 Bash 도구 호출만 가로챈다. 다른 에이전트·터미널의 커밋은 게이트 밖이다.
- python3 필요 (macOS 기본 포함).
