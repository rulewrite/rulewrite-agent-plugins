#!/usr/bin/env python3
"""workspace-cleanup: 세션이 서 있는 디렉터리를 없애는 Bash 명령을 차단하는 PreToolUse hook.

보호 대상은 명령이 실행될 디렉터리(hook 입력 cwd)와 세션 프로젝트 루트(CLAUDE_PROJECT_DIR), 그리고
각각의 모든 상위 디렉터리다. 이 중 하나를 지우거나 옮기는 순간 작업 디렉터리가 사라져 세션이 끊긴다.
"""
import json
import os
import re
import shlex
import sys

SELF_REASON = (
    "workspace-cleanup: 명령의 {token} (= {target}) 은(는) 이 세션이 서 있는 디렉터리({base})이거나 "
    "그 상위라서 차단됨. 지우거나 옮기면 작업 디렉터리가 사라져 세션이 끊긴다. "
    "이 세션에서는 실행하지 말고, 세션을 닫은 뒤 메인 워크트리에서 실행할 명령을 절대경로로 적어 "
    "사용자에게 인수인계할 것 (예: git -C <메인 워크트리> worktree remove {target})."
)
UNRESOLVED_REASON = (
    "workspace-cleanup: 삭제·이동 대상 {token} 에 변수·와일드카드·명령 치환이 섞여 있어 "
    "이 세션이 서 있는 디렉터리를 가리키는지 판정할 수 없어 차단됨. "
    "대상을 리터럴 절대경로로 적어 재시도할 것 (다른 워크트리를 지우는 중이면 그 경로를 그대로 적으면 통과)."
)
INTERNAL_ERROR_REASON = (
    "workspace-cleanup: 가드 훅 내부 오류({error})로 판정하지 못해 차단됨. "
    "대상을 리터럴 절대경로로 단순화해 재시도하거나 사용자에게 알릴 것."
)

VERBS = {"rm", "rmdir", "mv", "trash", "git"}
DESTRUCTIVE_WORDS = re.compile(r"\b(rm|rmdir|mv|trash|worktree)\b")
DYNAMIC = re.compile(r"[$`*?\[{]")
PARENT_SEGMENT = re.compile(r"(^|/)\.\.(/|$)")
SHELL_OPERATORS = {"&&", "||", "|", ";", "&", "(", ")"}
REDIRECTION = re.compile(r"^\d*(>>?|<<?)")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n[ \t]*\2[ \t]*(?=\n|$)", re.DOTALL)
GIT_GLOBAL_WITH_ARG = {"-c", "--exec-path", "--namespace", "--git-dir", "--work-tree"}


def emit_deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))
    sys.exit(0)


class ProtectedDirs:
    """세션 디렉터리들과 그 상위 전부. 존재하는 경로는 inode로, 없는 경로는 정규화 문자열로 대조한다."""

    def __init__(self, bases):
        self.bases = bases
        self.inodes = {}
        self.names = {}
        for base in bases:
            path = os.path.realpath(os.path.expanduser(base))
            while True:
                try:
                    stat = os.stat(path)
                    self.inodes.setdefault((stat.st_dev, stat.st_ino), base)
                except OSError:
                    pass
                self.names.setdefault(os.path.normcase(path), base)
                parent = os.path.dirname(path)
                if parent == path:
                    break
                path = parent

    def covers(self, path):
        """path가 보호 디렉터리 중 하나면 그 기준 디렉터리를, 아니면 None을 돌려준다."""
        try:
            stat = os.stat(path)
            hit = self.inodes.get((stat.st_dev, stat.st_ino))
            if hit:
                return hit
        except OSError:
            pass
        return self.names.get(os.path.normcase(os.path.realpath(path)))


def split_commands(tokens):
    """셸 연산자 기준으로 토큰을 단순 명령 단위로 나눈다."""
    commands = []
    current = []
    for token in tokens:
        if token in SHELL_OPERATORS:
            if current:
                commands.append(current)
            current = []
        else:
            current.append(token)
    if current:
        commands.append(current)
    return commands


def git_targets(words):
    """`git [글로벌] worktree remove|move ...` 의 (대상 토큰, -C 디렉터리 목록) 또는 None."""
    i = 1
    c_dirs = []
    while i < len(words) and words[i].startswith("-"):
        bare = words[i].split("=", 1)[0]
        if bare == "-C" and i + 1 < len(words):
            c_dirs.append(words[i + 1])
            i += 2
        elif bare in GIT_GLOBAL_WITH_ARG and "=" not in words[i]:
            i += 2
        else:
            i += 1
    if i + 1 >= len(words) or words[i] != "worktree" or words[i + 1] not in {"remove", "move"}:
        return None
    positionals = positional_args(words[i + 2:], flags_with_arg=set())
    if not positionals:
        return None
    return positionals[0], c_dirs


def positional_args(words, flags_with_arg):
    positionals = []
    i = 0
    while i < len(words):
        word = words[i]
        if word == "--":
            positionals.extend(words[i + 1:])
            break
        if REDIRECTION.match(word):
            # `>file`은 한 토큰, `> file`은 다음 토큰이 리디렉션 대상
            i += 2 if re.fullmatch(r"\d*(>>?|<<?)", word) else 1
            continue
        if word.startswith("-") and len(word) > 1:
            if word.split("=", 1)[0] in flags_with_arg and "=" not in word:
                i += 2
            else:
                i += 1
            continue
        if word != "{}":  # find -exec 의 자리표시자
            positionals.append(word)
        i += 1
    return positionals


def rm_removes_directories(words):
    for word in words[1:]:
        if word == "--":
            return False
        if word in {"-r", "-R", "--recursive", "-d", "--dir"}:
            return True
        if re.fullmatch(r"-[a-zA-Z]+", word) and set(word[1:]) & set("rRd"):
            return True
    return False


def destructive_targets(words):
    """단순 명령 하나에서 (대상 토큰, 기준 디렉터리 토큰 목록) 목록을 뽑는다.

    동사는 첫 토큰으로 고정하지 않는다 — `then rm`, `sudo -u me rm`, `timeout 5 rm` 처럼 앞에 무엇이 붙든 잡는다.
    """
    for start, word in enumerate(words):
        if os.path.basename(word) in VERBS:
            break
    else:
        return []
    words = words[start:]
    verb = os.path.basename(words[0])
    if verb == "git":
        found = git_targets(words)
        return [found] if found else []
    if verb == "rm":
        if not rm_removes_directories(words):
            return []
        return [(path, []) for path in positional_args(words[1:], flags_with_arg=set())]
    if verb in {"rmdir", "trash"}:
        return [(path, []) for path in positional_args(words[1:], flags_with_arg=set())]
    if verb == "mv":
        positionals = positional_args(words[1:], flags_with_arg={"-t", "--target-directory", "-S", "--suffix"})
        has_target_option = any(w.split("=", 1)[0] in {"-t", "--target-directory"} for w in words[1:])
        sources = positionals if has_target_option else positionals[:-1]
        return [(path, []) for path in sources]
    return []


def resolve_dir(token, current):
    """cd·-C 인자를 절대경로로. 판정 불가면 None."""
    if DYNAMIC.search(token):
        return None
    token = os.path.expanduser(token)
    if not os.path.isabs(token):
        if current is None:
            return None
        token = os.path.join(current, token)
    return token if os.path.isdir(token) else None


def directory_after_cd(words, current):
    """`cd <리터럴 하나>`만 따라간다. 그 외 형태(옵션·`-`·popd·실패하는 경로)는 알 수 없음(None)."""
    if words[0] == "popd":
        return None
    if len(words) == 1:
        return os.path.expanduser("~")
    if len(words) > 2 or words[1].startswith("-"):
        return None
    return resolve_dir(words[1], current)


def judge(token, base_dir, protected):
    """대상 토큰 하나의 판정: ('self', 절대경로, 기준) | ('unresolved', None, None) | None."""
    expanded = os.path.expanduser(token)
    dynamic = DYNAMIC.search(expanded)
    if dynamic:
        # 변수 앞의 리터럴 접두가 가리키는 디렉터리가 보호 대상이면 그 아래 무엇이 지워질지 알 수 없다
        prefix = expanded[: dynamic.start()]
        if not prefix or PARENT_SEGMENT.search(expanded[dynamic.start():]):
            return "unresolved", None, None
        if not os.path.isabs(prefix):
            if base_dir is None:
                return "unresolved", None, None
            prefix = os.path.join(base_dir, prefix)
        prefix_dir = prefix if prefix.endswith("/") else os.path.dirname(prefix)
        if protected.covers(prefix_dir):
            return "unresolved", None, None
        return None
    if not os.path.isabs(expanded):
        if base_dir is None:
            return "unresolved", None, None
        expanded = os.path.join(base_dir, expanded)
    hit = protected.covers(expanded)
    if hit:
        return "self", os.path.realpath(expanded), hit
    return None


def check_tokens(tokens, start_dir, protected):
    current = start_dir
    for words in split_commands(tokens):
        if words[0] in {"cd", "pushd", "popd"}:
            current = directory_after_cd(words, current)
            continue
        for token, c_dirs in destructive_targets(words):
            base_dir = current
            for c_dir in c_dirs:
                base_dir = resolve_dir(c_dir, base_dir)
            verdict = judge(token, base_dir, protected)
            if verdict and verdict[0] == "self":
                emit_deny(SELF_REASON.format(token=token, target=verdict[1], base=verdict[2]))
            if verdict and verdict[0] == "unresolved":
                emit_deny(UNRESOLVED_REASON.format(token=token))


def check_fallback(command, protected):
    """토큰화에 실패한 명령은 보호 디렉터리의 리터럴 절대경로가 삭제 동사 뒤에 보일 때만 막는다."""
    for base in protected.bases:
        for literal in {base, os.path.realpath(os.path.expanduser(base))}:
            pattern = r"\b(rm\s+-\S*\s|rmdir\s|trash\s|mv\s|worktree\s+(remove|move)\s)[^\n;|&]*" + re.escape(literal) + r"(?=[/\s'\"]|$)"
            if re.search(pattern, command):
                emit_deny(SELF_REASON.format(token=literal, target=os.path.realpath(os.path.expanduser(literal)), base=base))


def check(command, cwd):
    bases = [b for b in (cwd, os.environ.get("CLAUDE_PROJECT_DIR")) if b]
    if not bases:
        return
    protected = ProtectedDirs(bases)
    without_heredoc = HEREDOC.sub("", command)
    normalized = re.sub(r"(\|\||&&|[;|&()])", r" \1 ", without_heredoc.replace("\n", " ; "))
    try:
        tokens = shlex.split(normalized, posix=True)
    except ValueError:
        check_fallback(command, protected)
        return
    check_tokens(tokens, cwd, protected)


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    command = (data.get("tool_input") or {}).get("command") or ""
    if not DESTRUCTIVE_WORDS.search(command):
        return
    try:
        check(command, data.get("cwd"))
    except SystemExit:
        raise
    except Exception as error:  # 훅이 죽으면 기본이 통과라, 위험 동사가 있는 명령은 오류를 차단으로 돌린다
        emit_deny(INTERNAL_ERROR_REASON.format(error=f"{type(error).__name__}: {error}"))


if __name__ == "__main__":
    main()
