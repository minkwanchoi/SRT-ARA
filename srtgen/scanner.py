"""소스 트리를 훑어 예외사유 표기법을 수집하고 예외사유 단위로 묶는다."""
from __future__ import annotations

import fnmatch
import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from . import criteria, notation
from .lexer import Comment, Language, Lexed, language_for, mask_spans
from .notation import TEST_TYPES, TagHit

TAB_SIZE = 4
_HAS_NOTATION = re.compile(rb"(?i)srt[-_ ]")     # 표기법(또는 잘못 쓴 표기법)이 있을 만한 파일인지


@dataclass
class CommentInfo:
    """표기법이 든 주석 하나(이어진 // 주석은 한 덩어리). 잘못 쓴 주석을 화면에서 고칠 때 쓴다."""
    cid: int                # 파일 안에서의 순번
    kind: str               # "line" | "block"
    line: int
    end_line: int
    start: int              # \\n 기준 원문 오프셋 (주석 기호 포함)
    end: int
    raw: str                # 소스에 쓴 그대로
    before: List[Tuple[int, str]] = field(default_factory=list)   # 앞뒤 코드 몇 줄 (화면 표시용)
    after: List[Tuple[int, str]] = field(default_factory=list)


@dataclass
class Diagnostic:
    level: str      # "error" | "warning"
    file: str
    line: int
    message: str
    comment: Optional[CommentInfo] = field(default=None, compare=False)   # 문제가 있는 주석
    suggest: List[Tuple[str, str]] = field(default_factory=list, compare=False)  # (지금 글자, 고칠 글자)
    item: str = field(default="", compare=False)   # 예외사유 key ("S-C:1"). 내용 편집으로 고칠 수 있는 문제

    def __str__(self) -> str:
        label = "오류" if self.level == "error" else "경고"
        return f"[{label}] {self.file}:{self.line}: {self.message}"


@dataclass
class TagSite:
    """소스에서 태그 주석 하나가 놓인 자리. 본문을 소스에 되쓸 때 쓴다 (오프셋은 \\n 기준 원문)."""
    kind: str                           # "line" (//) | "block" (/* */)
    line: int
    tag_end: int                        # 태그 바로 뒤 (본문이 없을 때 넣을 자리)
    body: Optional[Tuple[int, int]]     # 중괄호를 포함한 본문의 범위
    indent: str                         # 주석이 시작하는 줄의 들여쓰기
    has_fields: bool = False
    ok: bool = True                     # 닫히지 않은 본문/주석이면 False
    clean: bool = True                  # 본문을 해석할 때 경고가 없었음
    field_spans: List[Tuple[str, int, int]] = field(default_factory=list)   # (항목, 시작, 끝)
    comment: Optional[CommentInfo] = None


@dataclass
class Block:
    """표기법 한 쌍(START~END) 또는 단독 태그가 가리키는 코드 조각."""
    test: str
    ex_id: int
    index: int
    file: str
    language: str
    tag_line: int
    start_line: int
    end_line: int
    function: str
    code: List[Tuple[int, str]]
    fields: Dict[str, str] = field(default_factory=dict)
    base_dir: str = ""
    written: str = ""    # 소스에 쓴 그대로의 식별자. 보고서에서 소스를 다시 찾는 열쇠이다
    sites: List[TagSite] = field(default_factory=list)   # 단독 태그 1개, 또는 START/END 2개
    ordinal: int = 0     # 같은 파일에서 같은 (유형, ID, 인덱스) 가 나온 순번

    @property
    def tag(self) -> str:
        return self.written or notation.format_tag(self.test, self.ex_id, self.index)

    @property
    def key(self) -> Tuple[str, int, int, int]:
        return (self.test, self.ex_id, self.index, self.ordinal)

    @property
    def editable(self) -> bool:
        return bool(self.sites) and all(s.ok for s in self.sites)

    @property
    def comment(self) -> Optional[CommentInfo]:
        """내용(본문)이 적힌 주석. 없으면 마지막 태그의 주석."""
        if not self.sites:
            return None
        return next((s for s in reversed(self.sites) if s.body), self.sites[-1]).comment

    @property
    def lines(self) -> str:
        if self.start_line == self.end_line:
            return str(self.start_line)
        return f"{self.start_line}~{self.end_line}"


@dataclass
class Occurrence:
    """예외사유가 발생한 위치 하나 (인덱스 1) 와 그 참조 코드 (인덱스 2~N)."""
    main: Block
    refs: List[Block] = field(default_factory=list)

    @property
    def fields(self) -> Dict[str, str]:
        merged: Dict[str, str] = {}
        for b in [self.main] + self.refs:
            for k, v in b.fields.items():
                merged.setdefault(k, v)
        return merged


@dataclass
class ExceptionItem:
    test: str
    ex_id: int
    occurrences: List[Occurrence]

    @property
    def tag(self) -> str:
        return notation.id_part(self.representative.main.tag)

    @property
    def representative(self) -> Occurrence:
        return self.occurrences[0]

    @property
    def same(self) -> List[Occurrence]:
        return self.occurrences[1:]

    @property
    def fields(self) -> Dict[str, str]:
        return self.representative.fields

    @property
    def count(self) -> int:
        return len(self.occurrences)


@dataclass
class ScanResult:
    items: List[ExceptionItem]
    diagnostics: List[Diagnostic]
    files_scanned: int = 0
    files_with_tags: int = 0
    paths: Dict[str, Path] = field(default_factory=dict)    # 표기법이 있는 파일의 실제 경로
    hashes: Dict[str, str] = field(default_factory=dict)    # 읽은 시점의 파일 내용 해시(SHA-1)

    def by_test(self, test: str) -> List[ExceptionItem]:
        return [i for i in self.items if i.test == test]

    @property
    def has_errors(self) -> bool:
        return any(d.level == "error" for d in self.diagnostics)


def decode_source(data: bytes, encoding: Optional[str] = None) -> Tuple[str, str]:
    """(내용, 인코딩). 되쓸 때 같은 인코딩을 쓰도록 판별한 인코딩을 함께 돌려준다."""
    if data.startswith(b"\xef\xbb\xbf"):
        candidates = ["utf-8-sig"]
    else:
        candidates = ["utf-8", "cp949"]
    if encoding:
        candidates = [encoding]
    for enc in candidates:
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1"), "latin-1"


def read_source(path: Path, encoding: Optional[str] = None) -> str:
    return decode_source(path.read_bytes(), encoding)[0]


def _logical_comments(lexed: Lexed) -> List[Tuple[Comment, List[Comment], str]]:
    """표기법이 들어 있는 주석을 (첫 주석, 포함된 주석들, 내용) 으로 돌려준다.

    본문이 여러 줄의 // 주석에 걸쳐 있으면 한 덩어리로 합친다.
    """
    out: List[Tuple[Comment, List[Comment], str]] = []
    comments = lexed.comments
    i = 0
    while i < len(comments):
        c = comments[i]
        if not notation.SUSPECT_RE.search(c.inner):
            i += 1
            continue
        parts = [c]
        text = c.inner
        if c.kind == "line":
            while notation.brace_balance(text) > 0 and i + 1 < len(comments):
                nxt = comments[i + 1]
                if nxt.kind != "line" or nxt.line != parts[-1].line + 1 or lexed.code_before(nxt):
                    break
                parts.append(nxt)
                text += "\n" + nxt.inner
                i += 1
        out.append((c, parts, text))
        i += 1
    return out


def comment_spans(text: str, lang: Language) -> List[Tuple[int, int]]:
    """표기법이 든 주석의 (시작, 끝) 오프셋. 순서가 CommentInfo.cid 이다 (text 는 줄바꿈 LF 기준)."""
    return [(first.start, parts[-1].end) for first, parts, _content in _logical_comments(Lexed(text, lang))]


def _snippet(lexed: Lexed, stripped: str, start: int, end: int) -> List[Tuple[int, str]]:
    """start~end 줄을 발췌한다. 표기법 주석은 지우고, 그 때문에 비게 된 줄은 뺀다."""
    rows: List[Tuple[int, str]] = []
    for n in range(start, end + 1):
        original = lexed.line_text(n)
        text = lexed.line_text(n, stripped).rstrip()
        if not text.strip() and original.strip():
            continue
        rows.append((n, text.expandtabs(TAB_SIZE)))
    while rows and not rows[0][1].strip():
        rows.pop(0)
    while rows and not rows[-1][1].strip():
        rows.pop()
    indents = [len(t) - len(t.lstrip()) for _, t in rows if t.strip()]
    cut = min(indents) if indents else 0
    return [(n, t[cut:]) for n, t in rows]


def scan_text(text: str, rel: str, lang: Language, base_dir: str = "") -> Tuple[List[Block], List[Diagnostic]]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    diags: List[Diagnostic] = []
    blocks: List[Block] = []
    if not notation.SUSPECT_RE.search(text):
        return blocks, diags
    lexed = Lexed(text, lang)
    logical = _logical_comments(lexed)

    spans: List[Tuple[int, int]] = []
    for _first, parts, _text in logical:
        spans += [(p.start, p.end) for p in parts]

    stripped = mask_spans(text, spans)

    current: List[Optional[CommentInfo]] = [None]

    def warn(line: int, msg: str, level: str = "warning", suggest: Optional[List[Tuple[str, str]]] = None,
             comment: Optional[CommentInfo] = None) -> None:
        diags.append(Diagnostic(level, rel, line, msg, comment or current[0], suggest or []))

    def function_name(test: str, line: int) -> str:
        f = lexed.function_at(line)
        if f is None and test == "S-M":
            f = lexed.function_after(line)
        return f.signature if f else ""

    counts: Dict[Tuple[str, int, int], int] = {}

    def make_block(hit: TagHit, tag_line: int, start: int, end: int, fields: Dict[str, str],
                   sites: List[TagSite]) -> None:
        if end < start:
            warn(tag_line, f"{hit.tag}: 끝 위치가 시작 위치보다 앞에 있습니다", "error")
            end = start
        key = (hit.test, hit.ex_id, hit.index)
        counts[key] = counts.get(key, 0) + 1
        blocks.append(Block(hit.test, hit.ex_id, hit.index, rel, lang.name, tag_line, start, end,
                            function_name(hit.test, start), _snippet(lexed, stripped, start, end),
                            fields, base_dir, hit.written, sites, counts[key]))

    open_starts: Dict[Tuple[str, int, int], List[Tuple[TagHit, int, int, Dict[str, str], TagSite]]] = {}

    for cid, (first, parts, content) in enumerate(logical):
        last = parts[-1]
        info = current[0] = CommentInfo(
            cid, first.kind, first.line, last.end_line, first.start, last.end, text[first.start:last.end],
            [(n, lexed.line_text(n)) for n in range(max(1, first.line - 2), first.line)],
            [(n, lexed.line_text(n)) for n in range(last.end_line + 1, min(lexed.line_count, last.end_line + 3) + 1)])
        # 합친 주석 내용의 위치를 원문 오프셋으로 바꾸기 위한 구간표
        segments: List[Tuple[int, int, int]] = []
        cpos = 0
        for p in parts:
            segments.append((cpos, p.inner_start, len(p.inner)))
            cpos += len(p.inner) + 1

        def to_file(pos: int, segments: List[Tuple[int, int, int]] = segments) -> int:
            for cstart, fstart, length in segments:
                if cstart <= pos <= cstart + length:
                    return fstart + pos - cstart
            return segments[-1][1] + segments[-1][2]

        indent = re.match(r"[ \t]*", lexed.line_text(first.line)).group(0)
        if not first.terminated:
            warn(first.line, "주석이 닫히지 않았습니다", "error")
        if first.kind == "block" and ("/*" in first.inner or "//" in first.inner):
            warn(first.line, "주석 안에 '/*' 또는 '//' 가 있습니다 (MISRA C:2012 Rule 3.1 위반 가능)")
        for bad in notation.loose_tags(content):
            fixed = notation.suggest_tag(bad)
            warn(first.line, f"예외사유 주석 규칙에 맞지 않는 식별자입니다: {bad}", "error", [(bad, fixed)] if fixed else None)
        for hit in notation.find_tags(content):
            test = TEST_TYPES[hit.test]
            for e in hit.errors:
                warn(first.line, f"{hit.tag}: {e}", "error")
            stray = re.match(r"[ \t]+(START|END)\b", content[hit.tag_span[1]:]) if hit.role is None else None
            if stray:
                warn(first.line, f"{hit.tag}: 식별자와 {stray.group(1)} 사이에 빈칸이 있습니다", "error",
                     [(hit.tag + stray.group(0), hit.tag + stray.group(1))])
            fields: Dict[str, str] = {}
            errs: List[str] = []
            if hit.body is not None:
                fields, errs = notation.parse_body(hit.body, test)
                for e in errs:
                    unknown = re.search(r"쓸 수 없는 항목입니다: @(.+)$", e)
                    near = notation.closest_field(test, unknown.group(1)) if unknown else None
                    warn(first.line, f"{hit.tag}: {e}" + (f" (@{near} 을(를) 뜻합니까?)" if near else ""),
                         suggest=[("@" + unknown.group(1), "@" + near)] if near else None)
            site = TagSite(
                first.kind, first.line, to_file(hit.tag_span[1]),
                (to_file(hit.body_span[0]), to_file(hit.body_span[1])) if hit.body_span else None,
                indent, bool(fields), first.terminated and not hit.errors, not errs, comment=info)
            if hit.body_span:
                inner = hit.body_span[0] + 1
                site.field_spans = [(k, to_file(inner + a), to_file(inner + b))
                                    for k, a, b in notation.field_spans(hit.body, test)]
            before = lexed.code_before(first)
            after = lexed.code_after(last)
            key = (hit.test, hit.ex_id, hit.index)
            if hit.role == "END":
                end = first.line if before else lexed.prev_code_line(first.line - 1)
                if not open_starts.get(key):
                    warn(first.line, f"{hit.tag}END 에 대응하는 START 가 없습니다", "error")
                    continue
                s_hit, s_line, start, s_fields, s_site = open_starts[key].pop()
                merged = dict(s_fields)
                merged.update(fields)
                make_block(s_hit, s_line, start, end if end is not None else start, merged, [s_site, site])
                continue
            if before:
                anchor: Optional[int] = first.line
            elif after:
                anchor = last.end_line
            else:
                anchor = lexed.next_code_line(last.end_line + 1)
            if anchor is None:
                warn(first.line, f"{hit.tag}: 가리키는 코드가 없습니다", "error")
                continue
            if hit.role == "START":
                open_starts.setdefault(key, []).append((hit, first.line, anchor, fields, site))
                continue
            start = end = anchor
            if hit.test == "S-M":
                # 메트릭은 함수 단위이므로 함수 선언부를 발췌한다
                f = lexed.function_at(anchor) or lexed.function_after(anchor)
                if f is not None:
                    start, end = f.start_line, f.open_line
            make_block(hit, first.line, start, end, fields, [site])

    for key, pending in open_starts.items():
        for hit, line, _start, _fields, site in pending:
            warn(line, f"{hit.tag}START 에 대응하는 END 가 없습니다", "error", comment=site.comment)
    return blocks, diags


def iter_sources(roots: Iterable[Path], excludes: Iterable[str] = ()) -> Iterable[Tuple[Path, str, Language]]:
    excludes = list(excludes)
    roots = [Path(r) for r in roots]
    many = len(roots) > 1     # 폴더가 여러 개면 파일명이 겹치지 않게 폴더 이름을 앞에 붙인다
    for root in roots:
        if root.is_file():
            lang = language_for(root.name)
            if lang:
                yield root, root.name, lang
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for name in sorted(filenames):
                lang = language_for(name)
                if lang is None:
                    continue
                path = Path(dirpath) / name
                rel = path.relative_to(root).as_posix()
                if any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(name, pat) for pat in excludes):
                    continue
                yield path, (f"{root.resolve().name}/{rel}" if many else rel), lang


def group(blocks: List[Block], diags: List[Diagnostic]) -> List[ExceptionItem]:
    """코드 조각을 예외사유(ID) 단위로 묶는다.

    같은 ID 의 인덱스 1 이 다시 나오면 동일사항(같은 사유의 다른 위치)으로 본다.
    본문을 가장 충실하게 쓴 위치가 대표가 된다.
    """
    by_id: Dict[Tuple[str, int], List[Block]] = {}
    for b in sorted(blocks, key=lambda b: (b.file, b.start_line, b.index)):
        by_id.setdefault((b.test, b.ex_id), []).append(b)

    items: List[ExceptionItem] = []
    for (test, ex_id), group_blocks in by_id.items():
        ttype = TEST_TYPES[test]
        occurrences: List[Occurrence] = []
        orphans: List[Block] = []
        for b in group_blocks:
            if b.index == 1:
                occurrences.append(Occurrence(b))
            elif occurrences and occurrences[-1].main.file == b.file:
                occurrences[-1].refs.append(b)
            else:
                orphans.append(b)
        item_key = f"{test}:{ex_id}"

        def note(level: str, block: Block, message: str, item_key: str = item_key) -> None:
            diags.append(Diagnostic(level, block.file, block.tag_line, message, block.comment, [], item_key))

        tag = notation.format_tag(test, ex_id)
        if not occurrences:
            first = orphans.pop(0)
            note("error", first, f"{tag}: 인덱스 1 이 없습니다 ({first.tag} 를 발생 위치로 처리)")
            occurrences.append(Occurrence(first))

        shared = {f.key for f in ttype.fields if not f.per_occurrence}

        def weight(o: Occurrence) -> int:
            return sum(1 for k in o.fields if k in shared)

        rep = max(occurrences, key=weight)   # 동률이면 먼저 나온 위치
        rep.refs.extend(orphans)
        tag = notation.id_part(rep.main.tag)
        spellings = sorted({notation.id_part(b.tag) for b in group_blocks})
        if len(spellings) > 1:
            note("warning", rep.main, f"{tag}: 같은 ID 를 서로 다르게 썼습니다: {', '.join(spellings)}")
        occurrences.remove(rep)
        occurrences.insert(0, rep)

        rep_fields = rep.fields
        if weight(rep) == 0:
            note("error", rep.main, f"{tag}: 예외사유 내용이 없습니다")
        for f in ttype.fields:
            if f.key == "FA내용" and criteria.derived_content(test, rep_fields):
                continue                # 규칙명·취약점명은 번호에서 찾을 수 있으면 쓰지 않아도 된다
            if weight(rep) and f.required and not f.per_occurrence and f.key not in rep_fields:
                note("warning", rep.main, f"{tag}: @{f.key} 항목이 없습니다")
        if weight(rep):                 # 시험 기준(criteria.py)에 맞는 값인지
            standard = rep_fields.get("기준", "") if test == "S-C" else ""
            if standard and criteria.coding_standard(standard) is None:
                names = ", ".join(criteria.coding_standards_for(rep.main.language)
                                  or [n for n, _l in criteria.CODING_STANDARDS])
                note("warning", rep.main, f"{tag}: 시험 기준에 없는 코딩 규칙 기준입니다: {standard} (기준: {names})")
            level = rep_fields.get("커버리지", "") if test == "D" else ""
            if level and criteria.coverage(level) is None:
                note("warning", rep.main, f"{tag}: 코드 실행률 기준은 문장, 분기, MC/DC 중 하나입니다: {level}")
            if test == "S-W" and criteria.cwe_id(rep_fields.get("취약점", "") + " " + rep_fields.get("Ref", "")) is None:
                note("warning", rep.main, f"{tag}: @취약점 또는 @Ref 에 CWE 번호(CWE-###)가 없습니다")
        for o in occurrences:
            for f in ttype.fields:
                if f.required and f.per_occurrence and f.key not in o.fields:
                    note("warning", o.main, f"{o.main.tag}: @{f.key} 항목이 없습니다")
        for o in occurrences[1:]:
            clash = [k for k, v in o.fields.items() if k in shared and rep_fields.get(k) != v]
            if clash:
                note("warning", o.main, f"{tag}: 대표 위치({rep.main.file}:{rep.main.tag_line})와 "
                                        f"내용이 다릅니다: {', '.join('@' + k for k in clash)}")
        items.append(ExceptionItem(test, ex_id, occurrences))

    order = list(TEST_TYPES)
    items.sort(key=lambda i: (order.index(i.test), i.ex_id))
    return items


def scan(roots: Iterable[Path], excludes: Iterable[str] = (), encoding: Optional[str] = None) -> ScanResult:
    """폴더(또는 소스 파일)를 훑어 수집한다."""
    return scan_entries(iter_sources(roots, excludes), encoding)


def scan_entries(entries: Iterable[Tuple[Path, str, Language]], encoding: Optional[str] = None) -> ScanResult:
    """(파일, 식별자, 언어) 목록을 수집한다. 프로젝트 파일에서 읽은 소스 구성에 쓴다."""
    blocks: List[Block] = []
    diags: List[Diagnostic] = []
    paths: Dict[str, Path] = {}
    hashes: Dict[str, str] = {}
    scanned = 0
    for path, rel, lang in entries:
        scanned += 1
        try:
            data = path.read_bytes()
        except OSError as e:
            diags.append(Diagnostic("error", rel, 0, f"파일을 읽을 수 없습니다 ({e.strerror})"))
            continue
        if not _HAS_NOTATION.search(data):
            continue
        file_blocks, file_diags = scan_text(decode_source(data, encoding)[0], rel, lang, str(path.parent))
        if file_blocks or file_diags:
            paths[rel] = path
            hashes[rel] = hashlib.sha1(data).hexdigest()
        blocks += file_blocks
        diags += file_diags
    items = group(blocks, diags)
    diags.sort(key=lambda d: (d.file, d.line))
    return ScanResult(items, diags, scanned, len(paths), paths, hashes)
