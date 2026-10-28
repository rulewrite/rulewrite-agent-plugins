#!/usr/bin/env python3
"""workspace-cleanup: 세션이 서 있는 디렉터리를 없애는 Bash 명령을 차단하는 PreToolUse hook.

보호 대상은 명령이 실행될 디렉터리(hook 입력 cwd), 이 세션의 첫 호출 디렉터리(세션이 처음 선 곳),
세션 프로젝트 루트(CLAUDE_PROJECT_DIR), 그리고 각각의 모든 상위 디렉터리다. 이 중 하나를 지우거나
옮기는 순간 작업 디렉터리가 사라져 세션이 끊긴다.
"""
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys

SELF_REASON = (
    "workspace-cleanup: 명령의 {token} (= {target}) 은(는) 이 세션이 서 있는 디렉터리({base})이거나 "
    "그 상위라서 차단됨. 지우거나 옮기면 작업 디렉터리가 사라져 세션이 끊긴다. "
    "이 디렉터리는 이 세션에서 건드리지 말고, 세션을 닫은 뒤 메인 워크트리에서 실행할 명령을 "
    "절대경로로 적어 사용자에게 인수인계할 것{example}."
)
WORKTREE_EXAMPLE = " (예: git -C <메인 워크트리> worktree remove {target})"
UNRESOLVED_REASON = (
    "workspace-cleanup: 삭제·이동 대상 {token} 에 변수·와일드카드·명령 치환이 섞여 있거나 기준 디렉터리를 "
    "따라갈 수 없어, 이 세션이 서 있는 디렉터리를 가리키는지 판정할 수 없어 차단됨. "
    "대상을 리터럴 절대경로로 적어 재시도할 것 (다른 워크트리를 지우는 중이면 그 경로를 그대로 적으면 통과)."
)
INTERNAL_ERROR_REASON = (
    "workspace-cleanup: 가드 훅 내부 오류({error})로 판정하지 못해 차단됨. "
    "대상을 리터럴 절대경로로 단순화해 재시도하거나 사용자에게 알릴 것."
)

VERBS = {"rm", "rmdir", "mv", "trash", "git", "find"}
DIRECTORY_CHANGERS = {"cd", "pushd", "popd"}
DESTRUCTIVE_WORDS = re.compile(r"\b(rm|rmdir|mv|trash|worktree|find)\b")
DYNAMIC = re.compile(r"[$`*?\[{]")
PARENT_SEGMENT = re.compile(r"(^|/)\.\.(/|$)")
SHELL_OPERATORS = {"&&", "||", "|", ";", "&", "(", ")"}
REDIRECTION = re.compile(r"^\d*(>>?|<<?)")
HEREDOC_MARKER = re.compile(r"(?<!<)<<-?(?!<)\s*(['\"]?)(\w+)\1")  # `<<<`(here-string)은 heredoc이 아니다
COMMAND_SUBSTITUTION = "$__CMDSUB__"
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

    def dirs_at_or_below(self, start):
        """start 자신이거나 그 아래에 있는 보호 디렉터리들을 (절대경로, 기준) 목록으로 돌려준다."""
        start = os.path.normcase(os.path.realpath(start))
        return [(path, base) for path, base in self.names.items() if path == start or path.startswith(start.rstrip("/") + "/")]

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


def strip_heredoc_bodies(command):
    """heredoc 본문 줄만 걷어낸다. 마커가 있는 줄의 나머지 명령(`; rm ...`)은 그대로 둔다."""
    lines = command.split("\n")
    kept = []
    i = 0
    while i < len(lines):
        kept.append(lines[i])
        markers = HEREDOC_MARKER.findall(lines[i])
        i += 1
        for _, terminator in markers:
            while i < len(lines) and lines[i].strip() != terminator:
                i += 1
            i += 1
    return "\n".join(kept)


def mask_command_substitutions(command):
    """`$(...)`와 백틱 구간을 자리표시자 하나로 바꿔, 안의 괄호·공백이 명령 분리에 끼지 않게 한다."""
    out = []
    i = 0
    while i < len(command):
        if command.startswith("$(", i):
            depth = 0
            j = i + 1
            while j < len(command):
                if command[j] == "(":
                    depth += 1
                elif command[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            out.append(COMMAND_SUBSTITUTION)
            i = j + 1
            continue
        if command[i] == "`":
            j = command.find("`", i + 1)
            out.append(COMMAND_SUBSTITUTION)
            i = len(command) if j < 0 else j + 1
            continue
        out.append(command[i])
        i += 1
    return "".join(out)


def split_commands(tokens):
    """셸 연산자 기준으로 토큰을 단순 명령 단위로 나눈다. 서브셸 괄호는 '('·')' 항목으로 남긴다."""
    commands = []
    current = []
    for token in tokens:
        # 단순 명령 한가운데의 `(`는 find의 그룹 연산자다. `)`는 그 짝이 열려 있을 때만 find 것이고, 아니면 서브셸을 닫는다
        if token == "(" and any(os.path.basename(w) == "find" for w in current):
            current.append(token)
            continue
        if token == ")" and current.count("(") > current.count(")"):
            current.append(token)
            continue
        if token in SHELL_OPERATORS:
            if current:
                commands.append(current)
            current = []
            if token in {"(", ")"}:
                commands.append(token)
        else:
            current.append(token)
    if current:
        commands.append(current)
    return commands


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


def git_worktree_target(words):
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


def rm_removes_directories(words):
    for word in words[1:]:
        if word == "--":
            return False
        if word in {"-r", "-R", "--recursive", "-d", "--dir"}:
            return True
        if re.fullmatch(r"-[a-zA-Z]+", word) and set(word[1:]) & set("rRd"):
            return True
    return False


FIND_LOGIC_OPERATORS = {"!", "-not", "-o", "-or", "(", ")"}
FIND_ACTIONS = {"-delete", "-exec", "-execdir", "-ok", "-okdir"}


def find_start_points(words):
    """`find <시작점들> ... -delete|-exec rm ...` 이면 시작점 목록, 아니면 빈 목록."""
    deletes = False
    for i, word in enumerate(words):
        if word == "-delete":
            deletes = True
        if word in {"-exec", "-execdir"} and i + 1 < len(words) and os.path.basename(words[i + 1]) in {"rm", "rmdir", "trash"}:
            deletes = True
    if not deletes:
        return []
    starts = []
    for word in words[1:]:
        if word.startswith("-") or word in {"(", "!"}:
            break
        starts.append(word)
    return starts or ["."]


def find_dir_at_risk(words, start, protected):
    """find가 start 아래를 훑다가 지울 수 있는 보호 디렉터리 하나를 (절대경로, 기준)으로, 없으면 None.

    디렉터리는 모든 테스트를 통과할 때만 지워진다. 평가할 수 있는 테스트(-name/-iname의 basename 패턴,
    -mindepth/-maxdepth, 디렉터리가 아닌 -type)만 걸러내고, 부정·선택 연산이 섞이면 걸러낼 수 없다고 본다.
    """
    candidates = protected.dirs_at_or_below(start)
    if not candidates:
        return None
    # find는 왼쪽부터 평가하므로 첫 액션 뒤의 테스트는 아무것도 걸러내지 못한다
    words = words[: next((i for i, w in enumerate(words) if w in FIND_ACTIONS), len(words))]
    if FIND_LOGIC_OPERATORS & set(words):
        return candidates[0]
    start_real = os.path.normcase(os.path.realpath(start)).rstrip("/")
    name_tests, min_depth, max_depth = [], 0, None
    for i, word in enumerate(words[:-1]):
        value = words[i + 1]
        if word == "-type" and value != "d":
            return None
        if word in {"-name", "-iname"}:
            name_tests.append((value, word == "-iname"))
        if word == "-mindepth" and value.isdigit():
            min_depth = int(value)
        if word == "-maxdepth" and value.isdigit():
            max_depth = int(value)
    for path, base in candidates:
        depth = 0 if path == start_real else path[len(start_real) + 1:].count("/") + 1
        if depth < min_depth or (max_depth is not None and depth > max_depth):
            continue
        basename = os.path.basename(path)
        if any(not fnmatch.fnmatchcase(basename.lower() if ignore_case else basename, pattern.lower() if ignore_case else pattern) for pattern, ignore_case in name_tests):
            continue
        return path, base
    return None


def destructive_targets(words):
    """동사로 시작하는 단순 명령에서 (대상 토큰, -C 디렉터리 목록, 동사) 목록을 뽑는다."""
    verb = os.path.basename(words[0])
    if verb == "git":
        found = git_worktree_target(words)
        return [(found[0], found[1], "git worktree")] if found else []
    if verb == "rm":
        if not rm_removes_directories(words):
            return []
        return [(path, [], verb) for path in positional_args(words[1:], flags_with_arg=set())]
    if verb in {"rmdir", "trash"}:
        return [(path, [], verb) for path in positional_args(words[1:], flags_with_arg=set())]
    if verb == "mv":
        positionals = positional_args(words[1:], flags_with_arg={"-t", "--target-directory", "-S", "--suffix"})
        has_target_option = any(w.split("=", 1)[0] in {"-t", "--target-directory"} for w in words[1:])
        sources = positionals if has_target_option else positionals[:-1]
        return [(path, [], verb) for path in sources]
    if verb == "find":
        return [(path, [], verb) for path in find_start_points(words)]
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


def directory_after_change(words, current):
    """`cd <리터럴 하나>`·`pushd <리터럴 하나>`만 따라간다. 그 외(옵션·`-`·popd·인자 없는 pushd·실패하는 경로)는 알 수 없음(None)."""
    verb, args = words[0], words[1:]
    if verb == "popd" or (verb == "pushd" and not args):
        return None
    if not args:
        return os.path.expanduser("~")
    if len(args) > 1 or args[0].startswith("-"):
        return None
    return resolve_dir(args[0], current)


def registered_worktrees_matching(token, base_dir):
    """git이 경로 없는 인자를 등록된 워크트리의 경로 접미(`/<인자>`)로 찾는 규칙을 따라 후보를 돌려준다."""
    if base_dir is None:
        return None
    try:
        listing = subprocess.run(["git", "-C", base_dir, "worktree", "list", "--porcelain"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    paths = [line[len("worktree "):] for line in listing.splitlines() if line.startswith("worktree ")]
    suffix = "/" + token.rstrip("/")
    return [path for path in paths if path == token or path.endswith(suffix)]


def judge(token, base_dir, protected, verb):
    """대상 토큰 하나의 판정: ('self', 절대경로, 기준) | ('unresolved',) | None."""
    expanded = os.path.expanduser(token)
    dynamic = DYNAMIC.search(expanded)
    if dynamic:
        # 변수 앞의 리터럴 접두가 가리키는 디렉터리가 보호 대상이면 그 아래 무엇이 지워질지 알 수 없다
        prefix = expanded[: dynamic.start()]
        if not prefix or PARENT_SEGMENT.search(expanded[dynamic.start():]):
            return ("unresolved",)
        if not os.path.isabs(prefix):
            if base_dir is None:
                return ("unresolved",)
            prefix = os.path.join(base_dir, prefix)
        prefix_dir = prefix if prefix.endswith("/") else os.path.dirname(prefix)
        if protected.covers(prefix_dir):
            return ("unresolved",)
        return None
    if not os.path.isabs(expanded):
        if base_dir is None:
            return ("unresolved",)
        expanded = os.path.join(base_dir, expanded)
    candidates = [expanded]
    if verb == "git worktree" and not os.path.exists(expanded):
        candidates = registered_worktrees_matching(token, base_dir)
        if candidates is None:
            return ("unresolved",)
    for candidate in candidates:
        hit = protected.covers(candidate)
        if hit:
            return "self", os.path.realpath(candidate), hit
    return None


def check_tokens(tokens, cwd, protected):
    current = cwd
    subshell_stack = []
    for words in split_commands(tokens):
        if words == "(":
            subshell_stack.append(current)
            continue
        if words == ")":
            if subshell_stack:
                current = subshell_stack.pop()
            continue
        # 동사·cd는 첫 토큰으로 고정하지 않는다 — `then rm`, `sudo -u me rm`, `builtin cd` 처럼 앞에 무엇이 붙든 잡는다
        for start, word in enumerate(words):
            if os.path.basename(word) in VERBS or word in DIRECTORY_CHANGERS:
                break
        else:
            continue
        if words[start] in DIRECTORY_CHANGERS:
            current = directory_after_change(words[start:], current)
            continue
        for token, c_dirs, verb in destructive_targets(words[start:]):
            base_dir = current
            for c_dir in c_dirs:
                base_dir = resolve_dir(c_dir, base_dir)
            verdict = judge(token, base_dir, protected, verb)
            if verb == "find" and verdict and verdict[0] == "self":
                # 시작점이 보호 디렉터리(세션 디렉터리이거나 그 상위)여도, 테스트가 그 아래 보호 디렉터리를 전부 걸러내면 안전하다
                at_risk = find_dir_at_risk(words[start:], verdict[1], protected)
                if not at_risk:
                    continue
                verdict = ("self", at_risk[0], at_risk[1])
            if verdict and verdict[0] == "self":
                example = WORKTREE_EXAMPLE.format(target=verdict[1]) if verb == "git worktree" else ""
                emit_deny(SELF_REASON.format(token=token, target=verdict[1], base=verdict[2], example=example))
            if verdict and verdict[0] == "unresolved":
                emit_deny(UNRESOLVED_REASON.format(token=token))


def check_fallback(command, protected):
    """토큰화에 실패한 명령은 보호 디렉터리의 리터럴 절대경로가 삭제 동사 뒤에 보일 때만 막는다."""
    for base in protected.bases:
        for literal in {base, os.path.realpath(os.path.expanduser(base))}:
            pattern = r"\b(rm\s+-\S*\s|rmdir\s|trash\s|mv\s|find\s|worktree\s+(remove|move)\s)[^\n;|&]*" + re.escape(literal) + r"(?=[/\s'\"]|$)"
            if re.search(pattern, command):
                emit_deny(SELF_REASON.format(token=literal, target=os.path.realpath(os.path.expanduser(literal)), base=base, example=""))


def session_start_dir(session_id, cwd):
    """세션의 첫 호출 디렉터리를 플러그인 데이터에 기억해 둔다. cd로 빠져나간 뒤에도 처음 선 곳을 보호하기 위해서다."""
    data_dir = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not data_dir or not session_id or not cwd:
        return None
    record = os.path.join(data_dir, "session-start-dirs", session_id)
    try:
        with open(record, encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        pass
    try:
        os.makedirs(os.path.dirname(record), exist_ok=True)
        with open(record, "w", encoding="utf-8") as f:
            f.write(cwd)
    except OSError:
        pass
    return cwd


def check(command, cwd, start_dir):
    bases = []
    for base in (cwd, start_dir, os.environ.get("CLAUDE_PROJECT_DIR")):
        if base and base not in bases:
            bases.append(base)
    if not bases:
        return
    protected = ProtectedDirs(bases)
    masked = mask_command_substitutions(strip_heredoc_bodies(command))
    normalized = re.sub(r"(\|\||&&|[;|&()])", r" \1 ", masked.replace("\n", " ; "))
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
    cwd = data.get("cwd")
    start_dir = session_start_dir(data.get("session_id"), cwd)  # 위험 동사가 없는 첫 호출에서도 기억해야 한다
    command = (data.get("tool_input") or {}).get("command") or ""
    if not DESTRUCTIVE_WORDS.search(command):
        return
    try:
        check(command, cwd, start_dir)
    except SystemExit:
        raise
    except Exception as error:  # hooks.json의 onFailure=block이 못 보는 판정 오류에도 사유를 남긴다
        emit_deny(INTERNAL_ERROR_REASON.format(error=f"{type(error).__name__}: {error}"))


if __name__ == "__main__":
    main()
