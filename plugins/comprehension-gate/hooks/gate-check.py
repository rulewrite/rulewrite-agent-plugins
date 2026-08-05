#!/usr/bin/env python3
"""comprehension-gate: 사용자 이해 확인(퀴즈 통과) 전 Claude의 git commit을 차단하는 PreToolUse hook."""
import json
import os
import re
import shlex
import subprocess
import sys

QUIZ_REASON = (
    "comprehension-gate: 이 커밋은 사용자의 이해 확인 전이라 차단됨. "
    "comprehension-gate:comprehension-gate 스킬을 실행해 literate diff 설명과 퀴즈로 "
    "사용자 이해를 확인한 뒤 재시도할 것. "
    "서브에이전트라면 커밋하지 말고 메인 에이전트에 커밋 단계를 넘길 것."
)
REPO_UNCLEAR_REASON = (
    "comprehension-gate: 커밋 대상 저장소를 특정할 수 없는 형태(복잡한 cd·-C 조합, "
    "변수·와일드카드 경로, --git-dir, 복수 commit 등)라 차단됨. "
    "단일 cd <경로> && git commit 또는 git -C <경로> commit, "
    "혹은 저장소 루트에서 옵션 없는 git commit 형태로 재시도할 것."
)
STAGING_BYPASS_REASON = (
    "comprehension-gate: 스테이징을 거치지 않는 커밋(-a·--include·--only·pathspec 등)은 "
    "이해 확인한 내용과 커밋되는 내용이 어긋날 수 있어 차단됨. "
    "git add로 stage한 뒤 git commit -m 형태로 재시도할 것."
)
CHAIN_REASON = (
    "comprehension-gate: 스테이징을 바꾸는 명령(git add 등)과 commit을 한 명령줄에 섞으면 "
    "이해 확인 시점과 커밋되는 내용이 어긋날 수 있어 차단됨. "
    "스테이징을 먼저 끝내고, 별도 명령으로 git commit 할 것."
)

SHELL_OPERATORS = {"&&", "||", "|", ";", "&", "(", ")"}
GIT_GLOBAL_WITH_ARG = {"-c", "--exec-path", "--namespace"}
INDEX_MUTATORS = {"add", "rm", "mv", "restore", "reset", "checkout", "stash", "apply", "merge", "cherry-pick", "revert", "rebase"}
COMMIT_FLAGS_WITH_ARG = {"-m", "--message", "-F", "--file", "--author", "--date", "--trailer", "--cleanup"}
COMMIT_SAFE_FLAGS = {
    "--amend", "--edit", "--no-edit", "--no-verify", "-n", "--verbose", "-v",
    "--quiet", "-q", "--signoff", "-s", "-S", "--gpg-sign", "--no-gpg-sign",
    "--allow-empty", "--allow-empty-message", "--no-status", "--dry-run",
}


def emit_deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))
    sys.exit(0)


def classify_tokens(tokens):
    """(커밋 감지 여부, deny 사유 또는 None, 대상 디렉터리 또는 None)을 돌려준다.

    사유 None인 감지는 마커 검증 대상이며, 대상 디렉터리는 cd 프리픽스·-C 옵션을
    해석한 결과다. 워크트리 작업처럼 세션 cwd 밖 저장소로의 커밋을 지원한다.
    """
    cd_target = None
    cd_unclear = False
    if "cd" in tokens:
        if tokens.count("cd") > 1 or tokens[0] != "cd" or len(tokens) < 3 or tokens[2] not in {"&&", ";"}:
            cd_unclear = True
        else:
            cd_target = tokens[1]
    subcommands = []
    commit_count = 0
    target = None
    i = 0
    while i < len(tokens):
        if tokens[i] != "git":
            i += 1
            continue
        i += 1
        c_target = None
        repo_unclear = False
        while i < len(tokens) and tokens[i].startswith("-"):
            bare = tokens[i].split("=", 1)[0]
            if bare == "-C":
                if c_target is not None:
                    repo_unclear = True
                elif i + 1 < len(tokens):
                    c_target = tokens[i + 1]
                i += 2
            elif bare in {"--git-dir", "--work-tree"}:
                repo_unclear = True
                i += 1 if "=" in tokens[i] else 2
            elif bare in GIT_GLOBAL_WITH_ARG and "=" not in tokens[i]:
                i += 2
            else:
                i += 1
        if i >= len(tokens):
            break
        subcommand = tokens[i]
        subcommands.append(subcommand)
        if subcommand != "commit":
            continue
        commit_count += 1
        if repo_unclear or cd_unclear:
            return True, REPO_UNCLEAR_REASON, None
        target = os.path.join(cd_target or "", c_target or "") or None
        if target and re.search(r"[$`*?\[]", target):
            return True, REPO_UNCLEAR_REASON, None
        i += 1
        while i < len(tokens):
            token = tokens[i]
            if token in SHELL_OPERATORS:
                break
            bare = token.split("=", 1)[0]
            if bare in COMMIT_FLAGS_WITH_ARG:
                i += 1 if "=" in token else 2
            elif bare in COMMIT_SAFE_FLAGS:
                i += 1
            else:
                return True, STAGING_BYPASS_REASON, None
    if "commit" not in subcommands:
        return False, None, None
    if commit_count > 1:
        return True, REPO_UNCLEAR_REASON, None
    if INDEX_MUTATORS & set(subcommands):
        return True, CHAIN_REASON, None
    return True, None, target


def classify_fallback(command):
    """shlex가 실패한(인용부 불균형 등) 명령의 최선 노력 판정. 옵션은 commit과 같은 줄에 온다고 가정.

    이 경로에선 cd·-C 경로 해석이 불가능하므로 보수적으로 차단한다.
    """
    matched = re.search(r"\bgit\b[^\n;|&]*?\bcommit\b", command)
    if not matched:
        return False, None, None
    prefix = command[: matched.start()]
    if re.search(r"(^|[;&|\n])\s*cd\s", prefix):
        return True, REPO_UNCLEAR_REASON, None
    if re.search(r"\s(-C|--git-dir|--work-tree)[=\s]", matched.group(0)):
        return True, REPO_UNCLEAR_REASON, None
    rest_of_line = command[matched.end():].split("\n", 1)[0]
    if re.search(r"(^|\s)-[a-zA-Z]*a[a-zA-Z]*\b|--all\b|--include\b|--only\b|(^|\s)-o\b", rest_of_line):
        return True, STAGING_BYPASS_REASON, None
    if re.search(r"\bgit\b[^\n;|&]*?\b(add|rm|mv|restore|reset|checkout|stash)\b", command):
        return True, CHAIN_REASON, None
    return True, None, None


def run_git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def main():
    data = json.load(sys.stdin)
    command = (data.get("tool_input") or {}).get("command") or ""
    cwd = data.get("cwd") or "."
    if "commit" not in command:
        return
    try:
        normalized = re.sub(r"(\|\||&&|[;|&()])", r" \1 ", command.replace("\n", " ; "))
        tokens = shlex.split(normalized, posix=True)
    except ValueError:
        tokens = None
    detected, reason, target = classify_tokens(tokens) if tokens is not None else classify_fallback(command)
    if not detected:
        return
    if reason:
        emit_deny(reason)
    if target:
        cwd = os.path.normpath(os.path.join(cwd, os.path.expanduser(target)))
        if not os.path.isdir(cwd):
            return  # 실제 셸에서도 cd·-C가 실패해 커밋이 실행되지 않음

    if run_git(["rev-parse", "--verify", "--quiet", "MERGE_HEAD"], cwd).returncode == 0:
        return  # 머지 종결 커밋은 Claude가 만든 변경이 아니므로 범위 밖
    if run_git(["diff", "--cached", "--quiet"], cwd).returncode == 0:
        return  # 빈 스테이징(메시지만 고치는 amend 등); 스테이징 우회 옵션은 위에서 차단됨
    tree = run_git(["write-tree"], cwd)
    git_dir = run_git(["rev-parse", "--git-dir"], cwd)
    if tree.returncode != 0 or git_dir.returncode != 0:
        return  # 충돌 인덱스·비저장소 등 git 스스로 커밋을 거부할 상태
    marker_path = os.path.join(cwd, git_dir.stdout.strip(), "comprehension-gate-pass")
    try:
        with open(marker_path) as marker:
            recorded = marker.read().strip()
    except OSError:
        recorded = ""
    if recorded == tree.stdout.strip():
        return
    emit_deny(QUIZ_REASON)


if __name__ == "__main__":
    main()
