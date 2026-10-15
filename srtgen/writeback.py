"""편집한 예외사유 내용을 소스코드의 표기법 주석에 되쓴다.

원칙
- 주석만 바꾼다. 저장하기 전에 (1) 주석을 뺀 코드가 글자 하나 달라지지 않았는지,
  (2) 다시 읽었을 때 요청한 내용 그대로인지, (3) 다른 예외사유가 그대로인지를 확인하고,
  하나라도 어긋나면 파일을 건드리지 않는다.
- 바뀐 항목만 고친다. 손대지 않은 항목은 개발자가 쓴 줄바꿈과 순서 그대로 둔다
  (형상관리에서 차이가 작게 보이도록). 그렇게 할 수 없는 모양이면 본문 전체를 다시 쓴다.
- 인코딩과 줄바꿈 형식은 원래대로 둔다.
"""
from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import imageinfo
from .lexer import Language, Lexed
from .notation import TEST_TYPES, TestType
from .scanner import Block, TagSite, comment_spans, decode_source, scan_text

WIDTH = 100       # 주석 한 줄의 목표 폭(표시 칸 수)
COMPACT = 40      # 이보다 짧은 단일 항목은 한 줄로 쓴다


class WritebackError(Exception):
    """소스에 반영할 수 없음. 파일은 바뀌지 않았다."""


class Conflict(WritebackError):
    """화면에서 읽은 뒤에 소스 파일이 바뀌었다."""


@dataclass
class FieldEdit:
    """블록 하나의 새 항목 전체. fields 에 없는 항목은 지운다(화면은 원래 항목에 바꾼 값을 합쳐 보낸다)."""
    test: str
    ex_id: int
    index: int
    ordinal: int
    fields: Dict[str, str]

    @property
    def key(self) -> Tuple[str, int, int, int]:
        return (self.test, self.ex_id, self.index, self.ordinal)


def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def normalize_value(value: str) -> str:
    """편집 화면의 한 줄을 한 문단으로 본다. 연속 공백과 빈 줄은 정리한다."""
    lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(p for p in (" ".join(line.split()) for line in lines) if p)


def _escape_braces(value: str) -> str:
    depth = 0
    for ch in value:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                break
    if depth == 0:
        return value
    return value.replace("{", "\\{").replace("}", "\\}")


def _wrap(text: str, width: int) -> List[str]:
    lines: List[str] = []
    current = ""
    for word in text.split(" "):
        # '*' 로 시작하는 줄은 주석 장식으로 읽히므로 줄 머리에 두지 않는다
        if current and display_width(current) + 1 + display_width(word) > width and not word.startswith("*"):
            lines.append(current)
            current = word
        else:
            current = word if not current else current + " " + word
    lines.append(current)
    return lines


def format_field(key: str, value: str, lead: str) -> str:
    """`@항목{내용}` 을 만든다. 첫 줄은 lead 뒤에 놓인다고 보고, 이어지는 줄에는 lead 를 붙인다."""
    head = "@%s{" % key
    pad = " " * display_width(head)
    width = max(30, WIDTH - display_width(lead.expandtabs(4)) - display_width(head))
    rows: List[Optional[str]] = []          # None 은 문단 구분(빈 줄)
    for n, para in enumerate(_escape_braces(value).split("\n")):
        if n:
            rows.append(None)
        for line in _wrap(para, width):
            rows.append((pad if rows else head) + line)
    rows[-1] += "}"
    return "\n".join([rows[0]] + [lead.rstrip() if r is None else lead + r for r in rows[1:]])


def format_body(fields: List[Tuple[str, str]], kind: str, indent: str) -> str:
    """본문 `{...}` 전체를 만든다. kind 가 "line" 이면 이어지는 줄마다 `//` 를 붙인다."""
    if not fields:
        return ""
    if len(fields) == 1 and "\n" not in fields[0][1] and display_width(fields[0][0] + fields[0][1]) <= COMPACT:
        return "{@%s{%s}}" % (fields[0][0], _escape_braces(fields[0][1]))
    lead = indent + ("//   " if kind == "line" else "    ")
    close = indent + ("// }" if kind == "line" else "}")
    return "\n".join(["{"] + [lead + format_field(k, v, lead) for k, v in fields] + [close])


def _is_lead(text: str, kind: str) -> bool:
    """줄 머리에서 항목 앞까지가 들여쓰기(와 주석 기호)뿐인가."""
    pattern = r"[ \t]*//[/!]*[ \t]*" if kind == "line" else r"[ \t]*(?:\*[ \t]*)?"
    return re.fullmatch(pattern, text) is not None


def _minimal(text: str, block: Block, target: TagSite, wanted: Dict[str, str],
             ttype: TestType) -> Optional[str]:
    """바뀐 항목만 고친다. 본문 모양이 단순하지 않으면 None (본문 전체를 다시 쓴다)."""
    if not wanted or not target.body or not target.clean or not target.field_spans:
        return None
    if any(s is not target and s.body for s in block.sites):
        return None
    keys = [k for k, _, _ in target.field_spans]
    if len(set(keys)) != len(keys) or set(keys) != set(block.fields):
        return None

    def line_start(pos: int) -> int:
        return text.rfind("\n", 0, pos) + 1

    changes: List[Tuple[int, int, str]] = []
    for key, start, end in target.field_spans:
        lead = text[line_start(start):start]
        if key not in wanted:
            eol = text.find("\n", end)
            eol = len(text) if eol < 0 else eol
            if not _is_lead(lead, target.kind) or text[end:eol].strip():
                return None
            changes.append((line_start(start), min(eol + 1, len(text)), ""))
        elif wanted[key] != block.fields[key]:
            if not _is_lead(lead, target.kind):
                return None
            changes.append((start, end, format_field(key, wanted[key], lead)))
    added = [f.key for f in ttype.fields if f.key in wanted and f.key not in keys]
    if added:
        close = target.body[1] - 1                       # 본문을 닫는 '}'
        first = target.field_spans[0][1]
        lead = text[line_start(first):first]
        if not _is_lead(text[line_start(close):close], target.kind) or not _is_lead(lead, target.kind):
            return None
        new_lines = "".join(lead + format_field(k, wanted[k], lead) + "\n" for k in added)
        changes.append((line_start(close), line_start(close), new_lines))
    new = text
    for start, end, replacement in sorted(changes, reverse=True):
        new = new[:start] + replacement + new[end:]
    return new


def _full(text: str, block: Block, target: TagSite, wanted: Dict[str, str], ttype: TestType) -> str:
    """본문 전체를 표준 모양으로 다시 쓴다."""
    ordered = [(f.key, wanted[f.key]) for f in ttype.fields if f.key in wanted]
    body = format_body(ordered, target.kind, target.indent)
    changes: List[Tuple[int, int, str]] = []
    for site in block.sites:
        if site is target:
            changes.append((site.body[0], site.body[1], body) if site.body else (site.tag_end, site.tag_end, body))
        elif site.body:
            changes.append((site.body[0], site.body[1], ""))
    new = text
    for start, end, replacement in sorted(changes, reverse=True):
        new = new[:start] + replacement + new[end:]
    return new


def _code_only(text: str, lang: Language) -> str:
    return re.sub(r"\s+", "", Lexed(text, lang).nocomment)


def _snapshot(blocks: List[Block], skip: Tuple[str, int, int, int]) -> Dict[tuple, tuple]:
    return {b.key: (tuple(sorted(b.fields.items())), tuple(t for _, t in b.code))
            for b in blocks if b.key != skip}


def _verify(old: str, new: str, rel: str, lang: Language, blocks: List[Block], block: Block,
            wanted: Dict[str, str]) -> None:
    if _code_only(new, lang) != _code_only(old, lang):
        raise WritebackError(f"{rel}: {block.tag} 반영 시 코드가 달라져 중단했습니다.")
    new_blocks, _ = scan_text(new, rel, lang)
    again = next((b for b in new_blocks if b.key == block.key), None)
    if again is None or again.fields != wanted:
        raise WritebackError(f"{rel}: {block.tag} 의 내용을 그대로 보존할 수 없어 중단했습니다.")
    if _snapshot(new_blocks, block.key) != _snapshot(blocks, block.key):
        raise WritebackError(f"{rel}: {block.tag} 반영 시 다른 예외사유가 달라져 중단했습니다.")


def rewrite(text: str, rel: str, lang: Language, edit: FieldEdit) -> str:
    """\\n 기준 원문에서 예외사유 하나의 내용을 바꾼 새 원문을 돌려준다."""
    ttype = TEST_TYPES.get(edit.test)
    if ttype is None:
        raise WritebackError(f"알 수 없는 시험 유형입니다: {edit.test}")
    blocks, _ = scan_text(text, rel, lang)
    block = next((b for b in blocks if b.key == edit.key), None)
    if block is None:
        raise Conflict(f"{rel}: SRT-{edit.test}-ID{edit.ex_id}-{edit.index} 을(를) 찾을 수 없습니다. "
                       "소스를 다시 읽으십시오.")
    if not block.editable:
        raise WritebackError(f"{rel}:{block.tag_line}: {block.tag} 의 주석이 닫히지 않아 편집할 수 없습니다. "
                             "소스에서 먼저 고치십시오.")

    target = next((s for s in reversed(block.sites) if s.body), block.sites[-1])
    wanted: Dict[str, str] = {}
    for raw_key, raw_value in edit.fields.items():
        fdef = ttype.field(raw_key)
        if fdef is None:
            raise WritebackError(f"{edit.test} 유형에서 쓸 수 없는 항목입니다: @{raw_key}")
        value = normalize_value(raw_value)
        if not value:
            continue
        if "*/" in value and target.kind == "block":
            raise WritebackError(f"@{fdef.key}: 내용에 '*/' 를 쓸 수 없습니다 (주석이 끝나 버립니다).")
        if re.search(r"\\[n{}]", value):
            raise WritebackError(f"@{fdef.key}: 내용에 \\n, \\{{, \\}} 표기를 쓸 수 없습니다.")
        if re.search(r"\\(?=\s|$)", value):
            raise WritebackError(f"@{fdef.key}: 낱말을 역슬래시(\\)로 끝낼 수 없습니다 (다음 줄이 이어 붙습니다).")
        wanted[fdef.key] = value
    if wanted == block.fields:
        return text

    new = _minimal(text, block, target, wanted, ttype)
    if new is not None:
        try:
            _verify(text, new, rel, lang, blocks, block, wanted)
            return new
        except WritebackError:
            pass                    # 본문 전체를 다시 쓰는 방법으로 한 번 더 시도한다
    new = _full(text, block, target, wanted, ttype)
    _verify(text, new, rel, lang, blocks, block, wanted)
    return new


def _restore_newlines(original: str, old: str, new: str) -> str:
    """바뀌지 않은 줄은 원래 줄바꿈(\\r\\n 또는 \\n)을 그대로 두고, 바뀐 줄은 파일의 주된 형식을 쓴다."""
    if "\r" not in original:
        return new
    orig_lines = original.split("\n")
    old_lines = old.split("\n")
    new_lines = new.split("\n")
    head = 0
    while head < min(len(old_lines), len(new_lines)) and old_lines[head] == new_lines[head]:
        head += 1
    tail = 0
    while (tail < min(len(old_lines), len(new_lines)) - head
           and old_lines[-1 - tail] == new_lines[-1 - tail]):
        tail += 1
    crlf = sum(1 for line in orig_lines[:-1] if line.endswith("\r"))
    middle_cr = "\r" if crlf * 2 >= len(orig_lines) - 1 else ""
    out = orig_lines[:head]
    out += [line + middle_cr for line in new_lines[head:len(new_lines) - tail]]
    out += orig_lines[len(orig_lines) - tail:] if tail else []
    if not tail and out:
        out[-1] = out[-1].rstrip("\r")      # 파일의 마지막 줄 뒤에는 줄바꿈이 없다
    return "\n".join(out)


def _load(path: Path, rel: str, expected_sha: Optional[str]) -> Tuple[bytes, str, str, str]:
    """(파일 바이트, 원문, 인코딩, 줄바꿈을 LF 로 바꾼 원문). 되쓸 수 없는 파일이면 예외."""
    try:
        data = path.read_bytes()
    except OSError as e:
        raise WritebackError(f"{rel}: 파일을 읽을 수 없습니다 ({e.strerror})")
    if expected_sha and hashlib.sha1(data).hexdigest() != expected_sha:
        raise Conflict(f"{rel}: 화면에서 읽은 뒤에 소스 파일이 바뀌었습니다. 소스를 다시 읽으십시오.")
    original, encoding = decode_source(data)
    if encoding == "latin-1":
        raise WritebackError(f"{rel}: 인코딩을 판별할 수 없어 반영하지 않았습니다.")
    if re.search(r"\r(?!\n)", original):
        raise WritebackError(f"{rel}: CR 만 쓰는 줄바꿈 형식은 지원하지 않습니다.")
    return data, original, encoding, original.replace("\r\n", "\n")


def apply_edits(path: Path, rel: str, lang: Language, edits: List[FieldEdit],
                expected_sha: Optional[str] = None) -> str:
    """파일 하나에 편집을 반영하고 새 내용의 해시를 돌려준다. 실패하면 파일은 그대로이다."""
    data, original, encoding, old = _load(path, rel, expected_sha)
    new = old
    for edit in edits:
        new = rewrite(new, rel, lang, edit)
    return _store(path, rel, data, original, encoding, old, new)


def replace_comment(path: Path, rel: str, lang: Language, cid: int, before: str, text: str,
                    expected_sha: Optional[str] = None) -> str:
    """잘못 쓴 표기법 주석을 고친 글로 바꾼다. 주석 밖의 코드가 달라지면 쓰지 않는다.

    cid 는 파일 안에서 표기법 주석의 순번이고, before 는 화면이 보여 준 그 주석의 원문이다
    (다른 주석을 고치는 일이 없도록 대조한다).
    """
    data, original, encoding, old = _load(path, rel, expected_sha)
    spans = comment_spans(old, lang)
    before = before.replace("\r\n", "\n")
    if not 0 <= cid < len(spans) or old[spans[cid][0]:spans[cid][1]] != before:
        raise Conflict(f"{rel}: 고치려는 주석이 소스와 다릅니다. 소스를 다시 읽으십시오.")
    text = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip("\n")
    start, end = spans[cid]
    if not text:                          # 주석을 지우는 경우: 앞의 빈칸, 주석만 있던 줄은 줄째로 없앤다
        while start > 0 and old[start - 1] in " \t":
            start -= 1
        if (start == 0 or old[start - 1] == "\n") and old[end:end + 1] == "\n":
            end += 1
    new = old[:start] + text + old[end:]
    if _code_only(new, lang) != _code_only(old, lang):
        raise WritebackError(f"{rel}: 주석 밖의 코드가 달라집니다. 주석 기호(/* */, //)가 제자리에 있는지, "
                             "주석이 아닌 글자가 들어가지 않았는지 확인하십시오.")
    return _store(path, rel, data, original, encoding, old, new)


ATTACH_DIR = "srt_attach"
ATTACH_TYPES = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".mmd")
ATTACH_LIMIT = 10 * 1024 * 1024


def save_attachment(source: Path, name: str, data: bytes, overwrite: bool = False) -> str:
    """근거자료(그림, 다이어그램 원본)를 소스 파일 옆 srt_attach 폴더에 저장하고 @첨부 에 쓸 경로를 돌려준다."""
    stem, suffix = os.path.splitext(os.path.basename(name.replace("\\", "/")))
    stem = re.sub(r"[^\w가-힣.\-]+", "_", stem).strip("._") or "attach"
    suffix = suffix.lower()
    if suffix not in ATTACH_TYPES:
        raise WritebackError(f"넣을 수 없는 파일 형식입니다: {suffix or name}")
    if len(data) > ATTACH_LIMIT:
        raise WritebackError("파일이 너무 큽니다 (10MB 까지).")
    folder = source.parent / ATTACH_DIR
    target = folder / (stem + suffix)
    n = 1
    while target.exists() and not overwrite and target.read_bytes() != data:
        n += 1
        target = folder / f"{stem}_{n}{suffix}"
    try:
        folder.mkdir(exist_ok=True)
        target.write_bytes(data)
    except OSError as e:
        raise WritebackError(f"{target.name}: 저장할 수 없습니다 ({e.strerror})")
    if suffix != ".mmd" and imageinfo.size(target) is None:
        target.unlink()
        raise WritebackError(f"{name}: 그림 파일이 아닙니다.")
    return f"{ATTACH_DIR}/{target.name}"


def _store(path: Path, rel: str, data: bytes, original: str, encoding: str, old: str, new: str) -> str:
    """바뀐 원문을 원래 인코딩과 줄바꿈으로 쓰고 새 해시를 돌려준다."""
    if new == old:
        return hashlib.sha1(data).hexdigest()
    try:
        out = _restore_newlines(original, old, new).encode(encoding)
    except UnicodeEncodeError as e:
        raise WritebackError(f"{rel}: 이 파일의 인코딩({encoding})으로 쓸 수 없는 글자가 있습니다: "
                             f"{e.object[e.start:e.end]!r}")
    try:
        path.write_bytes(out)       # 속성/권한을 유지하도록 같은 파일에 쓴다
    except OSError as e:
        raise WritebackError(f"{rel}: 파일에 쓸 수 없습니다 ({e.strerror}). 읽기 전용인지 확인하십시오.")
    return hashlib.sha1(out).hexdigest()
