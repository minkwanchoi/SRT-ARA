"""예외사유 표기법 정의.

    /*SRT-S-C-ID##-1{Comments}*/
      S : StaticTest      C : CodingRule     W : WeaknessCheck
      M : SourceCodeMetric                   D : DynamicTest
      ID## : Exception_ID##
      1~N : ExceptionIndexNumber, 1~N(START|END) : 1~N의 시작 또는 끝

Comments 는 ``@항목{내용}`` 의 나열이며, 사용할 수 있는 항목은 시험 유형마다 다르다.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from . import criteria


@dataclass(frozen=True)
class FieldDef:
    key: str                       # 표준 항목명
    aliases: Tuple[str, ...] = ()  # 논문 표기 등 호환 항목명
    required: bool = False         # 대표 예외사유에 없으면 경고
    per_occurrence: bool = False   # 동일사항 위치마다 따로 쓰는 항목
    help: str = ""
    choices: Tuple[str, ...] = ()  # 시험 기준에 있는 값 (화면에서 고를 수 있게 보여 준다. 다른 값도 쓸 수 있다)


@dataclass(frozen=True)
class TestType:
    code: str                 # 표기법 식별 문자
    name: str                 # 시험 유형 이름
    report: str               # 보고서 이름
    filename: str             # 출력 파일 이름
    default_field: str        # @항목 없이 내용만 쓴 경우 대입할 항목
    fields: Tuple[FieldDef, ...]
    title: str = ""           # 화면에 보이는 정식 명칭

    def field(self, key: str) -> Optional[FieldDef]:
        return _FIELD_INDEX[self.code].get(normalize_key(key))


_COMMON = (
    FieldDef("설명", ("코드설명", "description"), help="코드내용 아래에 쓰는 코드 설명"),
    FieldDef("첨부", ("근거자료", "attach"), help="근거자료 이미지 경로(여러 개는 ; 로 구분, '경로|캡션')"),
    FieldDef("비고", ("note",), per_occurrence=True, help="동일사항 표의 비고"),
)

TEST_TYPES: Dict[str, TestType] = {
    "S-C": TestType(
        "S-C", "정적시험-코딩규칙", "코딩규칙 점검 FA 사유서", "01_코딩규칙_FA사유서", "FA분석",
        (
            FieldDef("기준", ("코딩기준", "표준", "standard"), required=True, help="적용한 코딩 규칙 기준",
                     choices=tuple(name for name, _langs in criteria.CODING_STANDARDS)),
            FieldDef("규칙", ("규칙번호", "코딩규칙", "위반유형", "rule"), required=True,
                     help="위반한 규칙의 번호 (예: Rule 14.3, ES.20)"),
            FieldDef("FA내용", ("규칙명", "내용", "규칙내용"), required=True,
                     help="규칙명. 도구에 그 기준의 규칙 목록이 있으면(.NET, C# 등) 비워 두어도 번호로 찾아 채운다"),
            FieldDef("FA분석", ("분석", "사유"), required=True, help="거짓경보로 판단한 분석 내용"),
            FieldDef("결론", (), required=True, help="신뢰성/기능 영향에 대한 결론"),
            FieldDef("Ref", ("참조", "reference"), help="참조 문서"),
        ) + _COMMON, "정적시험-코딩규칙 검증",
    ),
    "S-W": TestType(
        "S-W", "정적시험-취약점점검", "취약점 점검 FA 사유서", "02_취약점_FA사유서", "FA분석",
        (
            FieldDef("취약점", ("위반유형", "CWE", "weakness"), required=True,
                     help="검출된 취약점 항목 (CWE 번호와 이름)", choices=criteria.weakness_choices()),
            FieldDef("FA내용", ("취약점명", "내용", "취약점내용"),
                     help="취약점의 이름. 비워 두면 CWE 번호로 찾아 채우고, 목록에 없는 CWE 는 @취약점에 번호 뒤로 적은 이름을 쓴다"),
            FieldDef("FA분석", ("분석", "사유"), required=True, help="거짓경보로 판단한 분석 내용"),
            FieldDef("결론", (), required=True, help="신뢰성/기능 영향에 대한 결론"),
            FieldDef("Ref", ("참조", "reference"), help="참조 문서(CWE 번호 등)"),
        ) + _COMMON, "정적시험-취약점 점검",
    ),
    "S-M": TestType(
        "S-M", "정적시험-소스코드메트릭", "소스코드메트릭 제한값 미달성 분석 보고서",
        "03_소스코드메트릭_미달성분석보고서", "미달성사유",
        (
            FieldDef("메트릭", ("metric",), required=True, help="메트릭 종류", choices=criteria.METRICS),
            FieldDef("제한값", ("기준", "limit"), required=True, help="메트릭 제한값"),
            FieldDef("측정값", ("measured",), required=True, per_occurrence=True, help="도구 측정값"),
            FieldDef("미달성사유", ("사유",), required=True, help="제한값을 충족하지 못한 사유"),
        ) + _COMMON, "소스코드 메트릭 점검",
    ),
    "D": TestType(
        "D", "동적시험", "SW신뢰성 동적시험 미달성 분석 보고서",
        "04_동적시험_미달성분석보고서", "미달성사유",
        (
            FieldDef("커버리지", ("실행률", "기준", "coverage"), required=True, help="달성하지 못한 코드 실행률 기준",
                     choices=tuple(name for name, _accepted in criteria.COVERAGES)),
            FieldDef("미달성사유", ("사유",), required=True, help="코드 실행률을 달성하지 못한 사유"),
            FieldDef("요구사항", ("Ref", "참조", "requirement"), help="관련 요구사항 식별자"),
        ) + _COMMON, "동적시험",
    ),
}


def normalize_key(key: str) -> str:
    return re.sub(r"[\s._]+", "", key).casefold()


_FIELD_INDEX: Dict[str, Dict[str, FieldDef]] = {}
for _t in TEST_TYPES.values():
    _idx: Dict[str, FieldDef] = {}
    for _f in _t.fields:
        for _name in (_f.key,) + _f.aliases:
            _idx[normalize_key(_name)] = _f
    _FIELD_INDEX[_t.code] = _idx


TAG_RE = re.compile(
    r"(?<![A-Za-z0-9_-])SRT-(S-C|S-W|S-M|D)-ID(\d+)(?:-(\d+)(START|END)?)?(?![A-Za-z0-9_-])"
)
# 표기법처럼 보이지만 문법에 맞지 않는 것을 찾기 위한 느슨한 패턴.
# 뒤쪽은 소문자, 밑줄, 공백으로 잘못 쓴 것(srt-s-c-id1-1, SRT_S_C_ID1_1, SRT S-C-ID1-1)을 잡는다.
# 경로 안의 글자(`srt_attach/SRT-S-W-ID1_그림.png`)는 식별자로 보지 않는다.
LOOSE_TAG_RE = re.compile(
    r"(?<![A-Za-z0-9_/\\.-])SRT-[A-Za-z]-?[A-Za-z0-9-]*"
    r"|(?i:(?<![A-Za-z0-9_/\\.-])SRT[-_ ]+[SD](?![A-Za-z])[-_A-Za-z0-9]*(?: +(?:ID|START|END)[-_A-Za-z0-9]*)*)"
)
# 주석에 표기법(또는 잘못 쓴 표기법)이 들어 있는지 가려내는 패턴
SUSPECT_RE = re.compile(r"SRT-|(?i:(?<![A-Za-z0-9])SRT[-_ ]+[SD](?![A-Za-z]))")


@dataclass
class TagHit:
    test: str
    ex_id: int
    index: int
    role: Optional[str]            # None | "START" | "END"
    body: Optional[str]            # {} 안의 원문 (없으면 None)
    errors: List[str]
    written: str = ""              # 소스에 쓴 그대로의 식별자 (START/END 제외)
    tag_span: Tuple[int, int] = (0, 0)             # 주석 내용 안에서 태그의 위치
    body_span: Optional[Tuple[int, int]] = None    # 중괄호를 포함한 본문의 위치 (닫힌 본문만)

    @property
    def tag(self) -> str:
        return self.written or format_tag(self.test, self.ex_id, self.index)


def format_tag(test: str, ex_id: int, index: Optional[int] = None) -> str:
    base = f"SRT-{test}-ID{ex_id}"
    return base if index is None else f"{base}-{index}"


def id_part(tag: str) -> str:
    """'SRT-S-C-ID01-2' -> 'SRT-S-C-ID01' (인덱스를 뺀 예외사유 식별자)."""
    m = re.match(r"SRT-(?:S-C|S-W|S-M|D)-ID\d+", tag)
    return m.group(0) if m else tag


def _match_brace(text: str, start: int) -> int:
    """text[start] == '{' 에 대응하는 '}' 위치. 없으면 -1."""
    depth = 0
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in "{}":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def brace_balance(text: str) -> int:
    """첫 태그 뒤에 오는 본문의 여는 중괄호가 닫히지 않은 개수."""
    m = TAG_RE.search(text) or LOOSE_TAG_RE.search(text)     # 잘못 쓴 식별자 뒤의 본문도 이어 붙인다
    if not m:
        return 0
    depth = 0
    i = m.end()
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in "{}":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    return depth


def find_tags(comment: str) -> List[TagHit]:
    """주석 한 개의 내용에서 표기법 태그와 본문을 찾는다."""
    hits: List[TagHit] = []
    pos = 0
    while True:
        m = TAG_RE.search(comment, pos)
        if not m:
            break
        errors: List[str] = []
        end = m.end()
        j = end
        while j < len(comment) and comment[j] in " \t\r\n":
            j += 1
        body: Optional[str] = None
        body_span: Optional[Tuple[int, int]] = None
        if j < len(comment) and comment[j] == "{":
            close = _match_brace(comment, j)
            if close < 0:
                errors.append("본문의 중괄호가 닫히지 않았습니다")
                body = comment[j + 1:]
                end = len(comment)
            else:
                body = comment[j + 1:close]
                end = close + 1
                body_span = (j, end)
        written = m.group(0)[:-len(m.group(4))] if m.group(4) else m.group(0)
        hits.append(TagHit(m.group(1), int(m.group(2)), int(m.group(3) or 1), m.group(4), body, errors,
                           written, m.span(), body_span))
        pos = end
    return hits


def loose_tags(comment: str) -> List[str]:
    """문법에 맞지 않는 SRT- 표기를 찾는다."""
    valid = [m.span() for m in TAG_RE.finditer(comment)]
    # 올바른 태그의 본문 안은 사유를 적는 글이므로 검사하지 않는다 (다른 식별자나 파일 이름을 적을 수 있다)
    valid += [hit.body_span for hit in find_tags(comment) if hit.body_span]
    bad = []
    for m in LOOSE_TAG_RE.finditer(comment):
        if not any(a <= m.start() < b for a, b in valid):
            bad.append(m.group(0).rstrip(" -_"))
    return bad


def suggest_tag(bad: str) -> Optional[str]:
    """잘못 쓴 식별자를 문법에 맞게 고친 것. 고칠 수 없으면 None."""
    s = re.sub(r"[_\s]+", "-", bad.strip().upper())
    s = re.sub(r"-{2,}", "-", s)
    s = re.sub(r"^SRT-?S-?([CWM])(?=-|I|1|L|\d)", r"SRT-S-\1", s)       # SRT-SC-… -> SRT-S-C-…
    s = re.sub(r"^SRT-?D(?=-|I|1D|LD|\d)", "SRT-D", s)
    s = re.sub(r"^(SRT-(?:S-[CWM]|D))-?(?:ID|1D|LD|I)-?(\d+)", r"\1-ID\2", s)   # 1D1, ID-1 -> ID1
    m = re.match(r"^(SRT-(?:S-[CWM]|D)-ID\d+-\d+)-?([A-Z]+)$", s)
    if m:                                                             # STRAT -> START
        close = difflib.get_close_matches(m.group(2), ["START", "END"], n=1, cutoff=0.5)
        s = m.group(1) + (close[0] if close else m.group(2))
    return s if s != bad and TAG_RE.fullmatch(s) else None


def closest_field(test: TestType, raw_key: str) -> Optional[str]:
    """그 시험 유형에서 쓸 수 없는 항목 이름과 가장 비슷한 표준 항목명."""
    names = {normalize_key(n): f.key for f in test.fields for n in (f.key,) + f.aliases}
    close = difflib.get_close_matches(normalize_key(raw_key), list(names), n=1, cutoff=0.5)
    return names[close[0]] if close else None


_DECOR_RE = re.compile(r"^[ \t]*\*+(?!/)[ \t]?")


def clean_value(raw: str) -> str:
    """여러 줄에 걸친 내용을 한 문단으로 합친다. 빈 줄과 \\n 은 줄바꿈으로 남긴다."""
    paragraphs: List[str] = []
    current: List[str] = []
    for line in raw.split("\n"):
        line = _DECOR_RE.sub("", line).strip()
        if line:
            current.append(line)
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    text = "\n".join(paragraphs)
    text = text.replace("\\n", "\n").replace("\\{", "{").replace("\\}", "}")
    return "\n".join(part.strip() for part in text.split("\n")).strip()


_KEY_RE = re.compile(r"@([^@{}\n]{1,30}?)\s*\{")


def field_spans(body: str, test: TestType) -> List[Tuple[str, int, int]]:
    """본문 안에서 `@항목{내용}` 하나하나의 위치. 반환: (표준 항목명, 시작, 끝) 목록.

    소스에 되쓸 때 바뀐 항목만 고치기 위한 것으로, 닫히지 않았거나 모르는 항목은 뺀다.
    """
    spans: List[Tuple[str, int, int]] = []
    pos = 0
    while True:
        m = _KEY_RE.search(body, pos)
        if not m:
            return spans
        close = _match_brace(body, m.end() - 1)
        if close < 0:
            return spans
        fdef = test.field(m.group(1).strip())
        if fdef is not None:
            spans.append((fdef.key, m.start(), close + 1))
        pos = close + 1


def parse_body(body: str, test: TestType) -> Tuple[Dict[str, str], List[str]]:
    """본문에서 @항목{내용} 을 추출한다. 반환: (표준 항목명 -> 내용, 오류 목록)."""
    fields: Dict[str, str] = {}
    errors: List[str] = []
    pos = 0
    found = False
    loose: List[str] = []
    while True:
        m = _KEY_RE.search(body, pos)
        if not m:
            loose.append(body[pos:])
            break
        loose.append(body[pos:m.start()])
        found = True
        open_at = m.end() - 1
        close = _match_brace(body, open_at)
        raw_key = m.group(1).strip()
        if close < 0:
            errors.append(f"@{raw_key} 의 중괄호가 닫히지 않았습니다")
            value = body[open_at + 1:]
            pos = len(body)
        else:
            value = body[open_at + 1:close]
            pos = close + 1
        fdef = test.field(raw_key)
        if fdef is None:
            errors.append(f"{test.code} 유형에서 쓸 수 없는 항목입니다: @{raw_key}")
            continue
        value = clean_value(value)
        if fdef.key in fields and fields[fdef.key] != value:
            fields[fdef.key] = fields[fdef.key] + "\n" + value
        else:
            fields[fdef.key] = value
    rest = clean_value("\n".join(loose))
    if rest:
        if found:
            errors.append(f"@항목 밖에 쓴 내용은 무시됩니다: {rest[:30]}")
        else:
            fields[test.default_field] = rest
    return fields, errors
