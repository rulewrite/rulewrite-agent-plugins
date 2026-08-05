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
    "comprehension-gate: cd 프리픽스나 -C·--git-dir·--work-tree가 붙은 커밋은 "
    "게이트가 대상 저장소를 특정할 수 없어 차단됨. "
    "저장소 루트를 작업 디렉터리로 두고 옵션 없는 git commit으로 재시도할 것."
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
GIT_GLOBAL_DENY = {"-C", "--git-dir", "--work-tree"}
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
    """(커밋 감지 여부, deny 사유 또는 None)을 돌려준다. 사유 None인 감지는 마커 검증 대상."""
    cd_present = "cd" in tokens
    subcommands = []
    i = 0
    while i < len(tokens):
        if tokens[i] != "git":
            i += 1
            continue
        i += 1
        repo_unclear = False
        while i < len(tokens) and tokens[i].startswith("-"):
            bare = tokens[i].split("=", 1)[0]
            if bare in GIT_GLOBAL_DENY:
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
        if repo_unclear or cd_present:
            return True, REPO_UNCLEAR_REASON
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
                return True, STAGING_BYPASS_REASON
    if "commit" not in subcommands:
        return False, None
    if INDEX_MUTATORS & set(subcommands):
        return True, CHAIN_REASON
    return True, None


def classify_fallback(command):
    """shlex가 실패한(인용부 불균형 등) 명령의 최선 노력 판정. 옵션은 commit과 같은 줄에 온다고 가정."""
    matched = re.search(r"\bgit\b[^\n;|&]*?\bcommit\b", command)
    if not matched:
        return False, None
    prefix = command[: matched.start()]
    if re.search(r"(^|[;&|\n])\s*cd\s", prefix):
        return True, REPO_UNCLEAR_REASON
    if re.search(r"\s(-C|--git-dir|--work-tree)[=\s]", matched.group(0)):
        return True, REPO_UNCLEAR_REASON
    rest_of_line = command[matched.end():].split("\n", 1)[0]
    if re.search(r"(^|\s)-[a-zA-Z]*a[a-zA-Z]*\b|--all\b|--include\b|--only\b|(^|\s)-o\b", rest_of_line):
        return True, STAGING_BYPASS_REASON
    if re.search(r"\bgit\b[^\n;|&]*?\b(add|rm|mv|restore|reset|checkout|stash)\b", command):
        return True, CHAIN_REASON
    return True, None


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
    detected, reason = classify_tokens(tokens) if tokens is not None else classify_fallback(command)
    if not detected:
        return
    if reason:
        emit_deny(reason)

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
