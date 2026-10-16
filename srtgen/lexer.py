"""언어별 주석 추출과 함수 범위 탐지.

구문 분석기 없이 주석/문자열 토큰만 구분한다. 주석으로 표현할 수 있는 언어는
LANGUAGES 에 항목을 추가하는 것으로 확장한다.
"""
from __future__ import annotations

import bisect
import functools
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

_STRING = r'"(?:\\.|[^"\\\n])*"'
_CHAR = r"'(?:\\.|[^'\\\n]){1,10}'"
_CPP_RAW = r'R"(?P<d>[^()\\\s]{0,16})\(.*?\)(?P=d)"'
_TRIPLE = r'"""(?:\\.|[^\\])*?"""'
_CS_RAW = r'"{3,}.*?"{3,}'
_CS_VERBATIM = r'(?:\$@|@\$|@)"(?:""|[^"])*"'


@dataclass(frozen=True)
class Language:
    name: str
    extensions: Tuple[str, ...]
    line_comments: Tuple[str, ...] = ("//",)
    block_comments: Tuple[Tuple[str, str], ...] = (("/*", "*/"),)
    strings: Tuple[str, ...] = (_STRING, _CHAR)
    brace_functions: bool = True   # { } 로 함수 본문을 감싸는 언어
    preprocessor: bool = False     # '#' 전처리 지시문 사용


LANGUAGES: Tuple[Language, ...] = (
    Language("C", (".c", ".h"), preprocessor=True),
    Language("C++", (".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".inl"),
             strings=(_CPP_RAW, _STRING, _CHAR), preprocessor=True),
    Language("Java", (".java",), strings=(_TRIPLE, _STRING, _CHAR)),
    Language("C#", (".cs",), strings=(_CS_RAW, _CS_VERBATIM, _STRING, _CHAR), preprocessor=True),
)


def language_for(filename: str) -> Optional[Language]:
    lower = filename.lower()
    for lang in LANGUAGES:
        if lower.endswith(lang.extensions):
            return lang
    return None


@functools.lru_cache(maxsize=None)
def _token_re(lang: Language) -> "re.Pattern[str]":
    parts: List[str] = []
    # 특수 문자열(raw, 여러 줄)은 일반 문자열보다 먼저 시도한다
    parts += [f"(?:{s})" for s in lang.strings[:-2]]
    for i, lc in enumerate(lang.line_comments):
        parts.append(f"(?P<lc{i}>{re.escape(lc)}[^\n]*)")
    for i, (o, c) in enumerate(lang.block_comments):
        parts.append(f"(?P<bc{i}>{re.escape(o)}.*?(?:{re.escape(c)}|\\Z))")
    parts += [f"(?:{s})" for s in lang.strings[-2:]]
    return re.compile("|".join(parts), re.S)


_PREPROC_RE = re.compile(r"^[ \t]*#(?:\\\n|[^\n])*", re.M)
_NOT_NL = re.compile(r"[^\n]")


def _blank(text: str) -> str:
    return _NOT_NL.sub(" ", text)


def mask_spans(text: str, spans: List[Tuple[int, int]]) -> str:
    out: List[str] = []
    pos = 0
    for a, b in spans:
        out.append(text[pos:a])
        out.append(_blank(text[a:b]))
        pos = b
    out.append(text[pos:])
    return "".join(out)


@dataclass
class Comment:
    kind: str        # "line" | "block"
    start: int       # 원문 오프셋
    end: int
    line: int        # 시작 줄(1부터)
    end_line: int
    inner: str       # 주석 기호를 뺀 내용
    terminated: bool = True
    inner_start: int = 0   # inner 가 시작하는 원문 오프셋


@dataclass
class FunctionRange:
    signature: str
    start_line: int   # 선언부 시작 줄
    open_line: int    # '{' 가 있는 줄
    end_line: int     # '}' 가 있는 줄


class Lexed:
    def __init__(self, text: str, lang: Language):
        self.lang = lang
        self.text = text
        self.line_starts = [0] + [m.end() for m in re.finditer("\n", text)]
        self.comments: List[Comment] = []
        string_spans: List[Tuple[int, int]] = []
        for m in _token_re(lang).finditer(text):
            group = m.lastgroup or ""
            if group.startswith("lc"):
                opener = lang.line_comments[int(group[2:])]
                inner = m.group(0)[len(opener):]
                inner = inner.lstrip("/!")
                self.comments.append(Comment("line", m.start(), m.end(), self.line_of(m.start()),
                                             self.line_of(m.start()), inner, True, m.end() - len(inner)))
            elif group.startswith("bc"):
                opener, closer = lang.block_comments[int(group[2:])]
                raw = m.group(0)
                terminated = raw.endswith(closer) and len(raw) >= len(opener) + len(closer)
                inner = raw[len(opener):len(raw) - len(closer)] if terminated else raw[len(opener):]
                self.comments.append(Comment("block", m.start(), m.end(), self.line_of(m.start()),
                                             self.line_of(max(m.start(), m.end() - 1)), inner, terminated,
                                             m.start() + len(opener)))
            else:
                string_spans.append(m.span())
        # nocomment: 주석만 지운 원문 (코드가 있는 줄인지 판단)
        self.nocomment = mask_spans(text, [(c.start, c.end) for c in self.comments])
        # nopp: 전처리 지시문까지 지운 것 (함수 선언부 문자열 추출)
        if lang.preprocessor:
            self.nopp = mask_spans(self.nocomment, [m.span() for m in _PREPROC_RE.finditer(self.nocomment)])
        else:
            self.nopp = self.nocomment
        # structure: 문자열까지 지운 것 (중괄호 구조 분석)
        self.structure = mask_spans(self.nopp, string_spans)
        self.string_spans = string_spans
        self._code_lines: Optional[List[bool]] = None
        self._functions: Optional[List[FunctionRange]] = None
        self._index: Optional[_FunctionIndex] = None

    # ---- 줄 번호 ----
    def line_of(self, offset: int) -> int:
        return bisect.bisect_right(self.line_starts, offset)

    @property
    def line_count(self) -> int:
        return len(self.line_starts)

    def line_text(self, line: int, source: Optional[str] = None) -> str:
        src = self.text if source is None else source
        a = self.line_starts[line - 1]
        b = self.line_starts[line] - 1 if line < len(self.line_starts) else len(src)
        return src[a:b]

    def is_code_line(self, line: int) -> bool:
        if self._code_lines is None:
            self._code_lines = [bool(s.strip()) for s in self.nocomment.split("\n")]
        return 1 <= line <= len(self._code_lines) and self._code_lines[line - 1]

    def next_code_line(self, line: int) -> Optional[int]:
        while line <= self.line_count:
            if self.is_code_line(line):
                return line
            line += 1
        return None

    def prev_code_line(self, line: int) -> Optional[int]:
        while line >= 1:
            if self.is_code_line(line):
                return line
            line -= 1
        return None

    def code_before(self, c: Comment) -> bool:
        return bool(self.nocomment[self.line_starts[c.line - 1]:c.start].strip())

    def code_after(self, c: Comment) -> bool:
        end = self.line_starts[c.end_line] if c.end_line < self.line_count else len(self.text)
        return bool(self.nocomment[c.end:end].strip())

    # ---- 함수 범위 ----
    # 중괄호 구조는 파일마다 한 번 훑지만, 선언부가 함수인지(_signature)와 줄 번호는 물어본 줄 근처의 것만 계산한다
    # (53단계: 수집 시간의 대부분이 모든 '{' 의 선언부 해석이었다). 결과는 모두 계산하던 때와 같다.
    def _functions_index(self) -> "_FunctionIndex":
        if self._index is None:
            self._index = _FunctionIndex(self)
        return self._index

    @property
    def functions(self) -> List[FunctionRange]:
        if self._functions is None:
            self._functions = self._functions_index().all() if self.lang.brace_functions else []
        return self._functions

    def function_at(self, line: int) -> Optional[FunctionRange]:
        """그 줄을 품은 함수 중 가장 안쪽(선언부가 가장 늦게 시작하는) 것."""
        if not self.lang.brace_functions:
            return None
        return self._functions_index().at(line)

    def function_after(self, line: int) -> Optional[FunctionRange]:
        """그 줄이나 그 뒤에서 선언부가 시작하는 첫 함수."""
        if not self.lang.brace_functions:
            return None
        return self._functions_index().after(line)


_STRUCT_TOKEN = re.compile(r"[{}();]")
_NOT_A_FUNCTION = {
    "if", "for", "while", "switch", "catch", "foreach", "lock", "using", "fixed", "synchronized",
    "return", "sizeof", "else", "do", "try", "when", "defined", "alignas", "decltype", "typeof",
}
# 선언부가 이 낱말로 시작하면 함수가 아니다 (매크로로 감싼 조건문 등: `if likely(x) {`)
_NOT_LEADING = {"if", "else", "for", "while", "switch", "case", "return", "goto", "catch", "foreach", "throw"}
_FIRST_WORD = re.compile(r"\s*([A-Za-z_]\w*)")
_ACCESS_LABEL = re.compile(r"\s*(?:public|private|protected)(?:\s+\w+)?\s*:(?!:)")
_CTOR_INIT = re.compile(r"\)\s*:(?!:)")
_NAME_TAIL = re.compile(r"(?:operator\s*(?:\(\s*\)|[^\s\w(]+|\s\w+)|[A-Za-z_~]\w*)\s*$")
_TAIL_OK = re.compile(
    r"\s*(?:(?:const|volatile|noexcept|override|final|throws|where|mutable)\b.*|->.*|&{1,2}|=\s*0)?\s*$",
    re.S,
)
_REJECT_PREFIX = re.compile(r"\b(?:new|return|throw|await|yield|co_return|co_await)\b")


def _signature(masked: str, source: str) -> Optional[str]:
    """'{' 앞 선언부가 함수 정의이면 정리한 선언문을, 아니면 None 을 돌려준다."""
    while True:
        m = _ACCESS_LABEL.match(masked)
        if not m:
            break
        masked, source = masked[m.end():], source[m.end():]
    m = _FIRST_WORD.match(masked)
    if m and m.group(1) in _NOT_LEADING:
        return None
    m = _CTOR_INIT.search(masked)
    if m:
        masked, source = masked[:m.start() + 1], source[:m.start() + 1]
    # 최상위 괄호 묶음을 뒤에서부터 찾는다
    groups: List[Tuple[int, int]] = []
    depth = 0
    start = -1
    for i, ch in enumerate(masked):
        if ch == "(":
            if depth == 0:
                start = i
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
            if depth == 0:
                groups.append((start, i))
    if not groups:
        return None
    open_at, close_at = groups[-1]
    if not _TAIL_OK.match(masked[close_at + 1:]):
        return None
    prefix = masked[:open_at]
    name = _NAME_TAIL.search(prefix)
    if not name:
        return None
    word = name.group(0).strip()
    if word in _NOT_A_FUNCTION:
        return None
    if not word.startswith("operator"):
        if "=" in prefix or _REJECT_PREFIX.search(prefix):
            return None
    return " ".join(source.split())


class _FunctionIndex:
    """함수 후보(괄호 밖의 '{' 와 그 앞 선언부)를 한 번 훑어 모아 두고, 선언부 해석은 물어볼 때 한다.

    후보 i 의 구간 [boundary, close] 는 서로 겹치지 않거나 한쪽이 다른 쪽을 품는다(중괄호가 짝을 이루므로).
    그래서 한 위치를 품는 후보는 '그 위치 앞에서 마지막으로 시작한 후보'와 그 바깥 후보들(parent)뿐이다.
    예전처럼 모든 후보를 해석해 고르던 것과 같은 결과를 내야 한다(tests 의 대조 시험이 지킨다)."""

    def __init__(self, lexed: Lexed):
        self.lexed = lexed
        s = lexed.structure
        self._ranges: dict = {}
        # 후보마다 [boundary, open, close, seq, parent]:
        #   boundary 선언부가 시작할 수 있는 곳(앞의 ; { } 바로 뒤), open '{' 위치,
        #   close 짝 '}' 위치(없으면 None: 함수로 보지 않는다), seq 닫힌 차례(예전 목록의 순서. 같은 조건이면 이 순서로 고른다),
        #   parent 바로 바깥 후보(-1: 없음)
        cands: List[list] = []
        stack: List[Optional[list]] = []        # 열린 '{' 마다 (후보 또는 None), 그 '{' 앞의 괄호 깊이
        depths: List[int] = []
        outer = -1                              # 가장 안쪽의 열린 후보
        depth = 0
        boundary = 0
        closed = 0
        for m in _STRUCT_TOKEN.finditer(s):
            pos = m.start()
            ch = s[pos]
            if ch == "(":
                depth += 1
            elif ch == ")":
                if depth:
                    depth -= 1
            elif ch == ";":
                if depth == 0:
                    boundary = pos + 1
            elif ch == "{":
                if depth == 0:
                    cand = [boundary, pos, None, -1, outer]
                    outer = len(cands)
                    cands.append(cand)
                    stack.append(cand)
                else:
                    stack.append(None)
                depths.append(depth)
                depth = 0
                boundary = pos + 1
            else:
                if stack:
                    cand = stack.pop()
                    depth = depths.pop()
                    if cand is not None:
                        cand[2] = pos
                        cand[3] = closed
                        closed += 1
                        outer = cand[4]
                boundary = pos + 1
        self.boundary = [c[0] for c in cands]
        self.open = [c[1] for c in cands]
        self.close: List[Optional[int]] = [c[2] for c in cands]
        self.seq = [c[3] for c in cands]
        self.parent = [c[4] for c in cands]

    def range(self, i: int) -> Optional[FunctionRange]:
        """후보 i 가 함수 정의이면 그 범위 (계산한 것은 기억한다)."""
        if i in self._ranges:
            return self._ranges[i]
        result = None
        close = self.close[i]
        if close is not None:
            lx = self.lexed
            b, o = self.boundary[i], self.open[i]
            head = lx.structure[b:o]
            sig = _signature(head, lx.nopp[b:o])
            if sig:
                lead = len(head) - len(head.lstrip())
                result = FunctionRange(sig, lx.line_of(b + lead), lx.line_of(o), lx.line_of(close))
        self._ranges[i] = result
        return result

    def all(self) -> List[FunctionRange]:
        order = sorted((self.seq[i], i) for i in range(len(self.open)) if self.close[i] is not None)
        return [f for f in (self.range(i) for _s, i in order) if f]

    def _containing(self, offset: int) -> List[int]:
        """offset 을 [boundary, close] 안에 품는 후보들."""
        i = bisect.bisect_right(self.boundary, offset) - 1
        found = []
        while i >= 0:
            close = self.close[i]
            if close is not None and close >= offset:
                found.append(i)
            i = self.parent[i]
        return found

    def at(self, line: int) -> Optional[FunctionRange]:
        starts = self.lexed.line_starts
        if not 1 <= line <= len(starts):
            return None
        lo = starts[line - 1]
        hi = (starts[line] if line < len(starts) else len(self.lexed.text) + 1) - 1
        # 그 줄과 겹치는 후보: 줄 처음·끝을 품는 것과 그 줄 안에서 시작하는 것
        cands = set(self._containing(lo)) | set(self._containing(hi))
        cands.update(range(bisect.bisect_left(self.boundary, lo), bisect.bisect_right(self.boundary, hi)))
        best: Optional[FunctionRange] = None
        best_seq = -1
        for i in cands:
            f = self.range(i)
            if f is None or not f.start_line <= line <= f.end_line:
                continue
            # 선언부가 가장 늦게 시작하는 것, 같으면 나중에 닫힌 것 (예전 순서에서 뒤의 것)
            if best is None or (f.start_line, self.seq[i]) > (best.start_line, best_seq):
                best, best_seq = f, self.seq[i]
        return best

    def after(self, line: int) -> Optional[FunctionRange]:
        starts = self.lexed.line_starts
        if line > len(starts):
            return None
        lo = starts[max(line, 1) - 1]
        best: Optional[FunctionRange] = None
        best_seq = -1
        # 선언부 시작은 '{' 앞이므로 '{' 가 그 줄보다 앞인 후보는 볼 필요가 없다. 후보는 위치 순이라 시작 줄도 순서대로다
        for i in range(bisect.bisect_left(self.open, lo), len(self.open)):
            f = self.range(i)
            if f is None or f.start_line < line:
                continue
            if best is not None and f.start_line > best.start_line:
                break
            # 시작 줄이 가장 앞인 것, 같으면 먼저 닫힌 것 (예전 순서에서 앞의 것)
            if best is None or self.seq[i] < best_seq:
                best, best_seq = f, self.seq[i]
        return best
