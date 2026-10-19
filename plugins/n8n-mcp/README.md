# n8n-mcp

self-hosted n8n 인스턴스의 MCP 서버에 연결한다.

## Codex

Codex는 서버 주소에 설정값을 끼워 넣지 못해, 플러그인은 서버를 띄우지 않는다. 서버를 직접 등록하면 토큰은 환경변수 `N8N_MCP_TOKEN`에서 읽는다.

```shell
codex mcp add n8n --url https://<도메인>/mcp-server/http --bearer-token-env-var N8N_MCP_TOKEN
```
