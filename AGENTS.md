# 플러그인 컴포넌트 작업 전 공식 문서 확인

skill·command·agent·hook·MCP 등 플러그인 컴포넌트를 추가·수정할 때 [code.claude.com/docs](https://code.claude.com/docs)에서 파일 위치·frontmatter·invoke 동작을 먼저 확인한 뒤 작업한다. 기억·추측에 의존하지 않음.

Claude Code의 plugin/skill 시스템은 빠르게 변하고 마이그레이션도 흔하다 (예: "Custom commands have been merged into skills"). 학습 시점 지식이 자주 어긋난다.

# 플러그인은 서로를 모른다

스킬·에이전트·훅의 설명과 본문에 다른 플러그인의 컴포넌트 이름을 적지 않는다. 스킬은 자기가 하는 일만 적고, 스킬 사이의 경계는 설치 환경에 맡긴다.

플러그인은 따로 설치된다. 다른 플러그인이 있다고 가정한 안내는 그것이 없는 환경에서 없는 스킬을 가리키거나 할 일을 떠넘기고, 상대 플러그인의 이름이 바뀌면 아무도 모르게 깨진다.
