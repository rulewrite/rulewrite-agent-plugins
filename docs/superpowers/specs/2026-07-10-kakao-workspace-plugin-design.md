# kakao-workspace 플러그인 설계

## 배경

로컬 `~/.claude.json`에 설정해 쓰던 사내 Atlassian MCP 서버(`jira`, `wiki`)를, notion·n8n 등 다른 MCP처럼 마켓 레포에 플러그인으로 모아둔다.

두 서버 모두 `mcp-atlassian` 패키지(uvx) 하나로 동작하며, 사내 Data Center에 Personal Access Token(stdio)으로 붙는다.

## 목표

- 사내 jira/wiki MCP를 마켓의 한 플러그인으로 정리
- 사용자는 개인 토큰 2개만 입력 (사내 도메인은 고정)
- 로컬 설정과 동일한 툴 네임스페이스(`mcp__jira__*`, `mcp__wiki__*`) 유지

## 비목표

- 다른 Atlassian 인스턴스(타 회사/타 도메인) 지원 — 사내 전용
- jira/wiki 외 컴포넌트(skill·command 등) — 이번 범위 아님. 다만 이름은 확장 여지를 남긴다(`-mcp` 접미사 없음).

## 설계

### 패키징

- 플러그인 1개(`kakao-workspace`) 안에 서버 2개(`jira`, `wiki`)를 정의한다.
- 서버를 하나로 합치지 않는 이유: `mcp-atlassian`은 `--jira-url`·`--confluence-url`을 한 프로세스에 함께 줄 수 있지만, 그러면 툴이 `mcp__atlassian__*` 하나로 합쳐져 로컬 네임스페이스와 달라진다. 로컬과 동일하게 2개로 둔다.

### 파일 구조

```
plugins/kakao-workspace/
├── .claude-plugin/
│   └── plugin.json      # 메타데이터 + userConfig (토큰 2개)
└── .mcp.json            # jira, wiki 두 서버 정의
```

### `.mcp.json`

```json
{
  "mcpServers": {
    "jira": {
      "type": "stdio",
      "command": "uvx",
      "args": ["mcp-atlassian", "--jira-url=https://jira.daumkakao.com"],
      "env": { "JIRA_PERSONAL_TOKEN": "${user_config.jira_token}" }
    },
    "wiki": {
      "type": "stdio",
      "command": "uvx",
      "args": ["mcp-atlassian", "--confluence-url=https://wiki.daumkakao.com"],
      "env": { "CONFLUENCE_PERSONAL_TOKEN": "${user_config.confluence_token}" }
    }
  }
}
```

- URL은 사내 고정값이라 하드코딩한다.
- 토큰만 `${user_config.*}`로 주입한다. 공식 문서상 이 치환은 MCP server config의 `env` 값에서 지원되며, 기존 `notion-mcp`가 동일 방식으로 동작 중이다.

### `plugin.json`

```json
{
  "name": "kakao-workspace",
  "description": "카카오 사내 Atlassian MCP 서버 — jira.daumkakao.com(지라)·wiki.daumkakao.com(컨플루언스)에 Personal Access Token(stdio)으로 연결.",
  "version": "1.0.0",
  "userConfig": {
    "jira_token": {
      "type": "string",
      "title": "Jira Personal Access Token",
      "description": "jira.daumkakao.com 로그인 > 아바타 > Profile > Personal Access Tokens > Create token 으로 발급.",
      "sensitive": true,
      "required": true
    },
    "confluence_token": {
      "type": "string",
      "title": "Confluence(Wiki) Personal Access Token",
      "description": "wiki.daumkakao.com 로그인 > 아바타 > Profile > Personal Access Tokens > Create token 으로 발급.",
      "sensitive": true,
      "required": true
    }
  }
}
```

- `sensitive: true`로 토큰을 마스킹·키체인 저장.
- 두 토큰 모두 `required`.

### 마켓 등록

`.claude-plugin/marketplace.json`의 `plugins` 배열에 항목을 추가한다.

```json
{
  "name": "kakao-workspace",
  "source": "./plugins/kakao-workspace",
  "description": "카카오 사내 Atlassian MCP 서버 — 지라·위키를 Personal Access Token(stdio)으로 연결."
}
```

## 검증

- `plugin.json`·`.mcp.json`·`marketplace.json`을 `python3 -m json.tool`로 JSON 유효성 확인.
- 실제 MCP 연결은 플러그인 설치 후 사용자가 확인(스펙 범위 밖).
