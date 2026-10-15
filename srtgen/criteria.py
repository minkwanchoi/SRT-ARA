"""SW 신뢰성 시험 기준.

출처: 「무기체계 소프트웨어 개발 및 관리 매뉴얼」 방위사업청 매뉴얼 제2024-6호(개정 2024.12.26.)
부록 7 '3. 시험 기준'과 사용자가 정리해 준 시험 종류별 기준.

기준이 개정되면 이 파일만 고친다. 표기법 항목의 선택지, 점검, 보고서가 여기서 값을 가져간다.
"""
from __future__ import annotations

import csv
import datetime
import io
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---- 따르는 매뉴얼의 판 ----
# 도구 한 버전은 매뉴얼 한 판을 따른다(사용자 확정, 2026-10-14). 개정되면 이 값과 아래 기준을 고치고 도구 버전을 올린다
# (CHANGELOG.md). 산출물(exceptions.json, 요약)과 판 이력에 이 값과 도구 버전이 적힌다.
MANUAL_TITLE = "무기체계 소프트웨어 개발 및 관리 매뉴얼"
MANUAL_EDITION = "제2024-6호"                  # 방위사업청 매뉴얼 번호
MANUAL_REVISED = "2024.12.26."                 # 개정일
MANUAL = f"{MANUAL_TITLE}, 방위사업청 매뉴얼 {MANUAL_EDITION}(개정: {MANUAL_REVISED})"


def basis() -> Dict[str, str]:
    """산출물이 어느 기준으로, 어느 도구 버전으로 만들어졌는지 (exceptions.json, 판 이력에 적는다)."""
    from . import __version__
    return {"매뉴얼": MANUAL, "매뉴얼 판": MANUAL_EDITION, "도구 버전": __version__}

# ---- 코딩규칙 검증: 적용하는 코딩 규칙 기준 (이름, 대상 언어) ----
CODING_STANDARDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("MISRA-C:2012", ("C",)),
    ("MISRA-C:2023", ("C",)),
    ("MISRA-C++:2008", ("C++",)),
    ("MISRA-C++:2023", ("C++",)),
    ("C++ Core Guidelines", ("C++",)),
    ("Code Conventions for the Java Programming Language", ("Java",)),
    ("C# Coding Conventions", ("C#",)),
    (".NET Framework Design Guidelines", ("C#",)),
)

def _data(name: str) -> dict:
    """함께 넣어 둔 번호·이름 목록. 파일이 없으면 빈 목록으로 동작한다 (그 목록의 선택지와 이름 채우기만 빠진다)."""
    try:
        return json.loads((Path(__file__).parent / "data" / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ---- 코딩규칙 검증: 규칙 번호 -> 규칙명. 공개되고 함께 넣을 수 있는 목록만 넣는다 ----
# C++ Core Guidelines (https://isocpp.github.io/CppCoreGuidelines/CppCoreGuidelines.html).
# .NET Framework Design Guidelines: .NET 코드 분석 품질 규칙(CA, 같은 표의 IL 포함). Microsoft 문서가 설계 규칙은
#   이 지침을 따른다고 밝힌다(quality-rules/design-warnings). dotnet/docs 저장소는 CC BY 4.0.
# MISRA C/C++ 의 규칙 글은 구매한 문서(https://misra.org.uk/publications/, 1인 사용 허락)에 있고 공개된 규칙명 목록이
# 없으므로 넣지 않는다: 규칙 번호와 규칙명은 작성자가 직접 적는다(화면의 '규칙 목록').
# C# Coding Conventions: .NET 코드 스타일 규칙(IDE). 같은 dotnet/docs 저장소(CC BY 4.0).
# Code Conventions for the Java Programming Language: 1999년판 목차의 절 번호와 제목. 고지가 비상업·회사 내부 사용만
#   허락하므로(Sun 저작권 표시 필요) 회사 내부에서만 쓴다(사용자 확정, 2026-10-14). 밖에 배포하면 이 목록을 뺀다.
_CG = _data("cpp_core_guidelines.json")
_JAVA = _data("java_code_conventions.json")
_CSHARP = _data("csharp_style_rules.json")
_DOTNET = _data("dotnet_quality_rules.json")
_CWE = _data("cwe_views.json")
RULE_TITLES: Dict[str, Dict[str, str]] = {
    "C++ Core Guidelines": _CG.get("rules", {}),
    "Code Conventions for the Java Programming Language": _JAVA.get("rules", {}),
    "C# Coding Conventions": _CSHARP.get("rules", {}),
    ".NET Framework Design Guidelines": _DOTNET.get("rules", {}),
}

# ---- 취약점 점검: 소프트웨어 취약점 점검(CWE-658/659/660) 및 보안약점 점검 목록 ----
# CWE-658(C), 659(C++), 660(Java) 에 든 약점: 번호 -> 이름 (https://cwe.mitre.org/data/definitions/658.html 등)
CWE_VIEWS: Dict[str, Dict[int, str]] = {
    view: {int(k): v for k, v in body.get("members", {}).items()}
    for view, body in _CWE.get("views", {}).items()
}
CWE_VIEW_LANGUAGES = {"658": "C", "659": "C++", "660": "Java"}


def _when(text: str) -> str:
    """원본에 적힌 날짜를 2026.06.14. 꼴로. 읽지 못하면 그대로."""
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
        try:
            return datetime.datetime.strptime(text.strip(), fmt).strftime("%Y.%m.%d.")
        except ValueError:
            pass
    return text.strip()


def _info(data: dict, key: str, label: str, source: str = "") -> Dict[str, str]:
    """목록의 버전(판·문서 날짜)과 가져온 곳. label 의 {} 에 날짜가 들어간다."""
    when = _when(str(data.get(key, "")))
    return {"version": label.format(when) if when else "", "source": source or str(data.get("source", "")),
            "fetched": str(data.get("fetched", ""))}


# 도구에 든 목록마다 버전과 가져온 곳 (화면의 '규칙 목록'에 보인다). 목록을 다시 받으면 원본의 값을 따라 바뀐다.
LIST_INFO: Dict[str, Dict[str, str]] = {
    "C++ Core Guidelines": _info(_CG, "edition", "{}판"),
    "Code Conventions for the Java Programming Language": _info(_JAVA, "revised", "{} 개정판"),
    "C# Coding Conventions": _info(_CSHARP, "page_date", "문서 날짜 {}"),
    ".NET Framework Design Guidelines": _info(_DOTNET, "page_date", "문서 날짜 {}"),
    **{f"CWE-{view}": _info(_CWE, "page_updated", "페이지 갱신 {}", f"https://cwe.mitre.org/data/definitions/{view}.html")
       for view in CWE_VIEW_LANGUAGES},
    "보안약점 점검 목록": {"version": f"매뉴얼 {MANUAL_EDITION}(개정: {MANUAL_REVISED})",
                     "source": f"{MANUAL_TITLE} 부록 7 '3. 시험 기준'", "fetched": ""},
}

# 보안약점 점검 목록: CWE-ID -> (내용, 코딩규칙/취약점 점검 항목과 중복 여부)
SECURITY_WEAKNESSES: Dict[int, Tuple[str, bool]] = {
    22: ("Improper Limitation of a Pathname to a Restricted Directory ('Path Traversal')", False),
    59: ("Improper Link Resolution Before File Access ('Link Following')", False),
    78: ("Improper Neutralization of Special Elements used in an OS Command ('OS Command Injection')", False),
    89: ("Improper Neutralization of Special Elements used in an SQL Command ('SQL Injection')", False),
    99: ("Improper Control of Resource Identifiers ('Resource Injection')", False),
    119: ("Improper Restriction of Operations within the Bounds of a Memory Buffer", True),
    134: ("Use of Externally-Controlled Format String", True),
    190: ("Integer Overflow or Wraparound", True),
    259: ("Use of Hard-coded Password", False),
    285: ("Improper Authorization", False),
    306: ("Missing Authentication for Critical Function", False),
    307: ("Improper Restriction of Excessive Authentication Attempts", False),
    312: ("Cleartext Storage of Sensitive Information", False),
    319: ("Cleartext Transmission of Sensitive Information", False),
    321: ("Use of Hard-coded Cryptographic Key", False),
    327: ("Use of a Broken or Risky Cryptographic Algorithm", False),
    330: ("Use of Insufficiently Random Values", False),
    494: ("Download of Code Without Integrity Check", False),
    521: ("Weak Password Requirements", False),
    615: ("Information Exposure Through Comments", False),
    732: ("Incorrect Permission Assignment for Critical Resource", False),
    759: ("Use of a One-Way Hash without a Salt", False),
    170: ("Improper Null Termination", True),
    209: ("Generation of Error Message Containing Sensitive Information", True),
    367: ("Time-of-check Time-of-use (TOCTOU) Race Condition", True),
    369: ("Divide By Zero", True),
    390: ("Detection of Error Condition Without Action", True),
    400: ("Uncontrolled Resource Consumption", True),
    404: ("Improper Resource Shutdown or Release", True),
    415: ("Double Free", True),
    416: ("Use After Free", True),
    457: ("Use of Uninitialized Variable", True),
    467: ("Use of sizeof() on a Pointer Type", True),
    469: ("Use of Pointer Subtraction to Determine Size", True),
    476: ("NULL Pointer Dereference", True),
    489: ("Active Debug Code", True),
    495: ("Private Data Structure Returned From A Public Method", True),
    496: ("Public Data Assigned to Private Array-Typed Field", True),
    497: ("Exposure of Sensitive System Information to an Unauthorized Control Sphere", True),
    562: ("Return of Stack Variable Address", True),
    587: ("Assignment of a Fixed Address to a Pointer", True),
    628: ("Function Call with Incorrectly Specified Arguments", True),
    676: ("Use of Potentially Dangerous Function", True),
    755: ("Improper Handling of Exceptional Conditions", True),
}

# ---- 소스코드 메트릭: 기준서의 예시. 종류와 제한값은 사업마다 신뢰성시험계획에서 정한다 ----
METRICS: Tuple[str, ...] = (
    "Cyclomatic Complexity",
    "Number of Call Levels",
    "Number of Function Parameters",
    "Number of Calling Functions",
    "Number of Called Functions",
    "Number of Executable Code Lines",
)

# ---- 동적시험: 코드 실행률 기준 (표시 이름, 받아들이는 표기) ----
COVERAGES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("문장(Statement)", ("문장", "statement", "문장실행률", "statementcoverage")),
    ("분기(Branch)", ("분기", "branch", "분기실행률", "branchcoverage")),
    ("MC/DC", ("mcdc", "mc/dc", "modifiedcondition/decisioncoverage")),
)


def _plain(text: str) -> str:
    return re.sub(r"[\s\-_.]+", "", text).casefold()


def coding_standard(value: str) -> Optional[str]:
    """쓴 글이 기준에 있는 코딩 규칙 기준이면 그 정식 이름을, 아니면 None 을 돌려준다."""
    want = _plain(value)
    for name, _langs in CODING_STANDARDS:
        if _plain(name) == want:
            return name
    return None


def coding_standards_for(language: str) -> Tuple[str, ...]:
    return tuple(name for name, langs in CODING_STANDARDS if language in langs)


def coverage(value: str) -> Optional[str]:
    want = _plain(value)
    for name, accepted in COVERAGES:
        if want == _plain(name) or want in (_plain(a) for a in accepted):
            return name
    return None


def cwe_id(text: str) -> Optional[int]:
    """글에서 처음 나오는 CWE 번호."""
    m = re.search(r"CWE[\s\-_]*(\d+)", text, re.I)
    return int(m.group(1)) if m else None


def cwe_name(cwe: Optional[int]) -> str:
    """CWE 이름. 보안약점 점검 목록의 표기를 먼저 쓰고, 없으면 CWE-658/659/660 의 이름을 쓴다."""
    if cwe in SECURITY_WEAKNESSES:
        return SECURITY_WEAKNESSES[cwe][0]
    return next((members[cwe] for members in CWE_VIEWS.values() if cwe in members), "")


def cwe_written_name(text: str) -> str:
    """취약점 칸에 CWE 번호 뒤로 적은 이름("CWE-667 Improper Locking" → "Improper Locking"). 첫 줄만 본다."""
    m = re.search(r"CWE[\s\-_]*\d+", text, re.I)
    if not m:
        return ""
    rest = text[m.end():].split("\n")[0].strip()
    if rest.startswith("(") and rest.endswith(")"):
        rest = rest[1:-1]
    return rest.lstrip(":-–—|·,. \t").strip()


def cwe_lists(cwe: Optional[int]) -> List[str]:
    """그 CWE 가 시험 기준의 어느 목록에 드는지: ["CWE-658", "CWE-659", "보안약점 점검 목록"] 등."""
    found = [f"CWE-{view}" for view, members in CWE_VIEWS.items() if cwe in members]
    return found + (["보안약점 점검 목록"] if cwe in SECURITY_WEAKNESSES else [])


def weakness_choices() -> Tuple[str, ...]:
    numbers = sorted(set(SECURITY_WEAKNESSES).union(*CWE_VIEWS.values()))
    return tuple(f"CWE-{n} {cwe_name(n)}" for n in numbers)


# ---- 화면의 '규칙 목록': 기준별로 도구에 든 목록을 보이고, 없으면 그 까닭을 보인다 ----
_MISRA_NOTE = ("MISRA 규칙 글은 구매한 문서(1인 사용 허락)에 있고 공개된 규칙명 목록이 없어 도구에 넣지 않았습니다. "
               "가지고 계신 문서를 보고 아래에 넣으십시오.")
RULE_LIST_NOTES: Dict[str, str] = {
    "MISRA-C:2012": _MISRA_NOTE,
    "MISRA-C:2023": _MISRA_NOTE,
    "MISRA-C++:2008": _MISRA_NOTE,
    "MISRA-C++:2023": _MISRA_NOTE,
}

# 공개본에는 재배포가 허락되지 않은 목록을 넣지 않는다: C++ Core Guidelines 는 개인·내부
# 업무용만, Java Code Conventions 는 비상업·내부 사용만 허락한다. 그 목록 파일이 없으면 화면에 까닭을 보인다.
RESTRICTED_LISTS: Dict[str, str] = {
    "C++ Core Guidelines": "cpp_core_guidelines.json",
    "Code Conventions for the Java Programming Language": "java_code_conventions.json",
}
for _name, _file in RESTRICTED_LISTS.items():
    if not RULE_TITLES.get(_name):
        RULE_LIST_NOTES[_name] = (
            "이 목록은 라이선스가 내부 사용만 허락해 공개본에 넣지 않았습니다. 원본을 보고 "
            "아래에 규칙 번호와 규칙명을 직접 넣거나 CSV 로 불러오십시오.")


def reference_lists() -> List[Tuple[str, str, Dict[str, str], Dict[str, str]]]:
    """도구에 든 번호·이름 목록: (묶음, 목록 이름, 번호 -> 이름, 버전·가져온 곳).
    코딩 규칙 기준, CWE 목록, 보안약점 점검 목록 순."""
    empty = {"version": "", "source": "", "fetched": ""}
    lists = [("코딩규칙 검증", name, dict(rules), LIST_INFO.get(name, empty))
             for name, rules in RULE_TITLES.items() if rules]
    for view, members in CWE_VIEWS.items():
        if members:
            name = f"CWE-{view} ({CWE_VIEW_LANGUAGES.get(view, '')})" if view in CWE_VIEW_LANGUAGES else f"CWE-{view}"
            lists.append(("취약점 점검", name, {f"CWE-{n}": members[n] for n in sorted(members)},
                          LIST_INFO.get(f"CWE-{view}", empty)))
    lists.append(("취약점 점검", "보안약점 점검 목록",
                  {f"CWE-{n}": SECURITY_WEAKNESSES[n][0] for n in sorted(SECURITY_WEAKNESSES)},
                  LIST_INFO["보안약점 점검 목록"]))
    return lists


_RULE_ID = re.compile(r"[A-Z][A-Za-z]*\.\d+[a-z]?")      # C++ Core Guidelines: ES.20, Enum.1
_ANALYZER_ID = re.compile(r"\b[A-Za-z]{2,3}\d{4}\b")       # .NET 코드 분석·스타일: CA1000, IL3000, IDE0001
# Java Code Conventions 의 절: 7.5, 10.5.3 ("10.5.3절"처럼 한글이 붙어도 찾는다)
_SECTION_ID = re.compile(r"(?<![A-Za-z0-9_.])\d+(?:\.\d+)*(?![A-Za-z0-9_.])")


def rule_title(standard: str, rule: str) -> str:
    """규칙 번호로 찾은 규칙명. 도구에 목록이 든 기준(MISRA 밖의 기준)에서만 찾을 수 있다."""
    titles = RULE_TITLES.get(coding_standard(standard) or "", {})
    candidates = (_RULE_ID.findall(rule) + [m.upper() for m in _ANALYZER_ID.findall(rule)]
                  + _SECTION_ID.findall(rule))
    return next((titles[m] for m in candidates if m in titles), "")


def derived_content(test: str, fields: Dict[str, str]) -> str:
    """FA내용(규칙명·취약점명)을 쓰지 않았을 때 번호에서 찾아 채울 글. 찾을 수 없으면 빈 글."""
    if test == "S-C":
        return rule_title(fields.get("기준", ""), fields.get("규칙", ""))
    if test == "S-W":
        # 목록의 이름이 먼저이고, 목록에 없는 CWE 는 @취약점에 번호 뒤로 적은 이름을 옮긴다(지어 넣지 않는다)
        weakness = fields.get("취약점", "")
        return cwe_name(cwe_id(weakness + " " + fields.get("Ref", ""))) or cwe_written_name(weakness)
    return ""


# ---- 사용자가 넣는 규칙 목록 ----
# 도구에 들어 있지 않은 기준(MISRA 등)의 규칙 번호와 규칙명은 사용자가 가진 문서를 보고 적어 둔다.
# 한 줄에 하나씩 "번호<탭>규칙명", "번호: 규칙명", "번호 | 규칙명", "Rule 14.3 규칙명" 모양을 받는다.
_RULE_SPLIT = re.compile(r"^(.+?)(?:\t+|\s*\|\s*|:\s+|\s{2,})(.+)$")
_RULE_HEAD = re.compile(r"^((?:Rule|Dir(?:ective)?\.?|규칙|지침)\s*[\w.\-]+|\S+)\s+(.+)$", re.I)


def parse_rule_lines(text: str) -> Tuple[Dict[str, str], List[int]]:
    """(번호 -> 규칙명, 나누지 못한 줄 번호 목록). 빈 줄과 # 로 시작하는 줄은 건너뛴다."""
    rules: Dict[str, str] = {}
    bad: List[int] = []
    for n, line in enumerate(text.replace("\r", "").split("\n"), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _RULE_SPLIT.match(line) or _RULE_HEAD.match(line)
        if not m or not m.group(1).strip() or not m.group(2).strip():
            bad.append(n)
            continue
        rules[" ".join(m.group(1).split())] = " ".join(m.group(2).split())
    return rules, bad


# 규칙 목록 파일(CSV)의 머리줄로 알아보는 열 이름
_ID_HEADS = {"번호", "규칙번호", "규칙 번호", "rule", "ruleid", "rule id", "id", "no", "no.", "number", "절", "절 번호"}
_TITLE_HEADS = {"규칙명", "규칙 이름", "이름", "제목", "내용", "title", "name", "rule name", "rulename", "description"}


def _decode(raw: bytes) -> Tuple[str, str]:
    """파일 글자: UTF-8(BOM 포함)을 먼저, 안 되면 CP949(엑셀이 한글 윈도우에서 저장한 CSV)."""
    for encoding, label in (("utf-8-sig", "UTF-8"), ("cp949", "CP949")):
        try:
            return raw.decode(encoding), label
        except UnicodeDecodeError:
            pass
    raise ValueError("글자 인코딩을 알 수 없습니다. UTF-8 이나 CP949(ANSI)로 저장한 파일을 고르십시오.")


def parse_rule_file(name: str, raw: bytes) -> dict:
    """규칙 목록 파일을 읽는다. CSV(쉼표·세미콜론·탭)는 열로, 그 밖(TXT 등)은 한 줄에 "번호<탭>규칙명" 또는 "번호: 규칙명".
    돌려주는 값: rules([번호, 규칙명] 순서대로), skipped(읽지 못한 줄 번호), encoding, header(머리줄을 건너뛰었는지)."""
    text, encoding = _decode(raw)
    if not name.lower().endswith((".csv", ".tsv")):
        found, bad = parse_rule_lines(text)
        return {"rules": [[k, v] for k, v in found.items()], "skipped": bad, "encoding": encoding, "header": False}
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel_tab if name.lower().endswith(".tsv") else csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    id_col, title_col, header = 0, 1, False
    first = next((i for i, r in enumerate(rows) if any(c.strip() for c in r)), None)
    if first is not None:
        heads = [" ".join(c.split()).lower() for c in rows[first]]
        ids = [i for i, h in enumerate(heads) if h in _ID_HEADS]
        titles = [i for i, h in enumerate(heads) if h in _TITLE_HEADS]
        if ids or titles:                     # 머리줄이 있으면 그 이름으로 열을 고른다
            header = True
            id_col = ids[0] if ids else 0
            title_col = titles[0] if titles else (1 if id_col == 0 else 0)
    rules: Dict[str, str] = {}
    bad: List[int] = []
    for n, row in enumerate(rows, 1):
        if not any(c.strip() for c in row) or (header and n - 1 == first):
            continue
        rid = " ".join(row[id_col].split()) if id_col < len(row) else ""
        title = " ".join(row[title_col].split()) if title_col < len(row) else ""
        if rid.startswith("#"):
            continue
        if not rid or not title:
            bad.append(n)
            continue
        rules[rid] = title
    return {"rules": [[k, v] for k, v in rules.items()], "skipped": bad, "encoding": encoding, "header": header}
