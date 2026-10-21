# comprehension-gate

에이전트가 만든 변경을 사용자가 이해했다고 증명(literate diff 설명 + 퀴즈 통과)하기 전까지 `git commit`을 차단하는 인지적 부채 속도 조절기. Geoffrey Litt의 [Understanding is the new bottleneck](https://www.geoffreylitt.com/2026/07/02/understanding-is-the-new-bottleneck.html)에서 착안했고, 설명 순서(배경→직관→코드)와 이해도 퀴즈 형식은 같은 저자의 [explain-diff 프롬프트](https://gist.github.com/geoffreylitt/a29df1b5f9865506e8952488eac3d524)를 따랐다. 그 글의 댓글에서 지적된 문제(보기 길이 편차, 정답 위치 편향)는 이 플러그인에서 정답 자리를 무작위로 뽑는 방식으로 보완했다.

## 동작

1. PreToolUse hook이 에이전트의 `git commit`을 가로채, 퀴즈 통과 기록(인덱스 트리 해시)이 현재 스테이징과 일치할 때만 통과시킨다.
2. 차단되면 에이전트가 스킬을 따라 배경→직관→워크스루 순서의 설명과 이해도 퀴즈를 진행한다.
3. 퀴즈를 통과하면 기록이 남고 커밋이 통과된다. 스테이징이 바뀌면 기록이 무효화되어 다시 걸린다.

게이트 생략이 필요하면 대화에서 직접 지시한다 (예: "이 커밋은 게이트 생략해").

## 범위 밖 (의도된 설계)

- 사용자가 터미널에서 직접 하는 커밋, `git push`, PR 생성은 막지 않는다.
- merge·cherry-pick·revert 등 Git이 대신 만드는 커밋은 게이트 대상이 아니다.

## 한계

- 에이전트가 통과 기록 스크립트를 임의 실행하는 우회를 물리적으로 차단할 수는 없다 (스킬 지침으로 금지).
- 셸을 한 겹 감싼 간접 실행(`sh -c 'git commit …'` 등)은 인용된 인자가 토큰 하나로 남아 감지하지 못한다. 통과 기록 임의 실행과 같은 고의 우회 계열로, 스킬 지침으로만 금지한다.
- 커밋을 대신 실행하는 스크립트(커밋 메시지 검사 래퍼 등)를 거친 커밋도 명령줄에 `git commit`이 드러나지 않아 감지하지 못한다.
- Claude Code·Codex의 셸 명령만 가로챈다. 터미널 등 그 밖의 커밋은 게이트 밖이다.
- Codex에서 실행 폴더를 따로 지정(`workdir`)한 커밋은 hook이 그 폴더를 몰라 놓칠 수 있다.
- python3 필요 (macOS 기본 포함).
