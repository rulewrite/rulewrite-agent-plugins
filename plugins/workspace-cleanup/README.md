# workspace-cleanup

git 작업 공간의 잔재(머지 끝난 브랜치, 소멸한 워크트리, 임시 파일, 잔류 프로세스)를 근거 확인과 승인을 거쳐 정리하는 스킬과, 정리 중 세션이 자기 발밑을 지우지 못하게 막는 훅으로 이루어진다.

## 구성

- `skills/workspace-cleanup/` — 정리 절차 스킬. "브랜치 정리하자", "세션 꺼도 되게 치워줘" 등에 발동.
- `hooks/own-worktree-guard.py` — PreToolUse(Bash) 훅. 스킬을 거치지 않은 정리에서도 동작한다.

## 훅이 막는 것

세션이 서 있는 디렉터리(훅 입력 `cwd`), 세션이 처음 선 디렉터리(첫 Bash 호출의 `cwd`를 `CLAUDE_PLUGIN_DATA/session-start-dirs/<session_id>`에 기억), 프로젝트 루트(`CLAUDE_PROJECT_DIR`), 그리고 각각의 모든 상위 디렉터리를 대상으로 하는 아래 명령을 차단한다. 처음 선 디렉터리를 기억하는 이유는 `cwd`가 `cd`를 따라가기 때문이다 — 한 호출에서 `cd <메인>`으로 빠져나간 뒤 다음 호출에서 원래 워크트리를 지우는 것도 같은 사고다. 경로는 `~` 확장·심볼릭 링크 해소 후 inode로 대조하므로 대소문자만 다른 경로(macOS)나 `/tmp`↔`/private/tmp` 같은 표기 차이로 빠져나가지 못한다.

- `git worktree remove <경로|이름>`, `git worktree move <경로|이름> <새 위치>` (`-C`·`cd` 반영. 경로가 없는 인자는 git처럼 등록된 워크트리의 경로 접미로 찾는다)
- `rm -r*/-R*/-d <경로>`, `rmdir <경로>`, `trash <경로>`
- `mv <경로> <어딘가>`
- `find <시작점> ... -delete`, `find <시작점> ... -exec rm|rmdir|trash` (시작점부터 그 아래 세션 디렉터리까지 중 하나라도 지워질 수 있으면 차단. `-name`/`-iname` 패턴이 그 디렉터리 이름에 안 맞거나, `-mindepth`/`-maxdepth` 범위 밖이거나, `-type`이 디렉터리가 아니면 걸러진 것으로 보고 통과. `!`·`-not`·`-o`·괄호가 섞이면 걸러낼 수 없다고 보고 차단. `-path`·`-regex`는 평가하지 않는다)

`if ...; then rm`, `sudo -u me rm`, `builtin cd` 처럼 예약어·래퍼 뒤에 와도 잡는다. 차단 사유에는 적중한 절대경로를 적고, `git worktree` 명령일 때만 세션을 닫은 뒤 메인 워크트리에서 실행할 인수인계 예시를 붙인다.

대상 경로에 변수·와일드카드·브레이스·명령 치환이 섞여 있으면 그 앞의 리터럴 접두가 가리키는 디렉터리로 판정한다. 그 디렉터리가 세션 디렉터리의 하위이거나 무관한 곳이면 통과(`rm -rf dist/*`, `rm -rf /tmp/scratch/$ID`), 접두가 비었거나 그 디렉터리가 세션 디렉터리 이상이거나 뒤에 `..`가 오면 "판정 불가"로 차단한다(`rm -rf "$W"`, `rm -rf ../w*`, `rm -rf ../$(basename "$PWD")`). 이때는 다른 워크트리를 지우는 중이어도 걸리므로, 대상을 리터럴 절대경로로 적어 재시도하면 된다.

`cd`·`pushd`는 리터럴 경로 하나짜리만 따라간다. `cd -`, 옵션, `popd`, 인자 없는 `pushd`, 존재하지 않는 경로 뒤의 상대경로 대상은 "판정 불가"로 차단한다. 서브셸 `( cd ... )` 안의 `cd`는 바깥에 적용하지 않는다. heredoc 본문은 명령으로 보지 않으므로 인수인계 명령을 파일에 적는 것은 막히지 않는다(마커 줄에 `;`로 이어 붙인 명령은 본다). `$(...)`·백틱 안은 명령으로 보지 않는다.

훅이 기동에 실패하면(python3 부재 등) `hooks.json`의 `onFailure: block`이 Bash 호출을 막고, 판정 중 예외는 위험 동사(`rm`·`rmdir`·`mv`·`trash`·`worktree`·`find`)가 있는 명령에 한해 사유를 담아 차단한다.

## 한계

- 셸 토큰 하나로 뭉친 간접 실행은 보지 못한다: `bash -c "..."`, `sh cleanup.sh`, git alias, `xargs rm -rf`, 스크립트 언어의 `rmtree`.
- 다른 세션이 이 세션의 워크트리를 지우는 것은 막지 못한다. 훅은 자기 세션만 안다.
- 세션 도중 EnterWorktree로 들어간 워크트리는 "처음 선 디렉터리"가 아니라서, 거기서 `cd`로 나온 뒤 지우는 호출은 못 본다. Claude Code가 그 워크트리에 거는 lock이 `git worktree remove`를 거부하는 데 기댄다.
- 플러그인을 켜기 전에 시작한 세션은 첫 Bash 호출 시점의 `cwd`를 처음 선 디렉터리로 기억한다.
- 변수 값 자체가 `..`인 경우(`X=..; rm -rf dist/$X`)는 접두만 보는 판정이라 통과한다.
- Codex는 셸 도구에 호출별 실행 폴더(`workdir`)를 줄 수 있는데 그 값이 훅 입력에 실리지 않는다(openai/codex#37251 등). 그 폴더 기준의 상대경로 대상은 세션 디렉터리 기준으로 잘못 해석될 수 있다. 절대경로 대상은 영향 없다.

## 호환

- Claude Code: 플러그인 설치만으로 동작한다.
- Codex: 같은 `hooks/hooks.json`을 읽고 `CLAUDE_PLUGIN_ROOT`도 넣어 준다. 훅 입력의 `cwd`는 세션 작업 디렉터리이고 셸 명령은 매번 거기서 시작하므로(호출 간 `cd` 유지 없음) 세션 디렉터리 보호는 그대로 된다. 단 훅은 Codex 데스크톱에 수동 설치한 플러그인에서만 켜지고 사용자가 훅을 신뢰로 표시해야 돈다.

## 요구 사항

- python3 (macOS 기본 포함)
- 훅 기동 실패까지 차단하려면 Claude Code v2.1.295 이상(`onFailure` 지원). 그 전 버전은 기동 실패 시 통과한다.

## 테스트

```bash
bash plugins/workspace-cleanup/tests/own-worktree-guard.test.sh
```
