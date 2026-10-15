"""개발도구(IDE)의 프로젝트 파일과 makefile 에서 소스 구성을 읽어 트리로 만든다.

지원: Visual Studio(.sln, .vcxproj, .csproj), Microchip(Atmel) Studio(.atsln, .cproj, .cppproj),
Eclipse 계열(CDT, Code Composer Studio, Xilinx SDK/Vitis, Wind River Workbench, Java:
.project/.cproject/.classpath), Makefile, CMake, IAR(.ewp, .eww), Keil uVision(.uvprojx, .uvproj),
Maven(pom.xml), Gradle, 그리고 폴더와 낱개 소스 파일.

빌드 도구를 실행하지 않고 파일만 읽으므로, 조건문·셸 호출 등으로 정해지는 소스는 놓칠 수 있다.
해석하지 못한 부분은 Project.warnings 에 남긴다.
"""
from __future__ import annotations

import fnmatch
import glob
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from .lexer import LANGUAGES, Language, language_for
from .scanner import iter_sources

MAKEFILE_NAMES = ("makefile", "gnumakefile")
ECLIPSE_FILES = (".project", ".cproject", ".ccsproject", ".wrproject", ".classpath")
GRADLE_FILES = ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts")
SOURCE_EXTS = tuple(ext for lang in LANGUAGES for ext in lang.extensions)
SKIP_DIRS = {"bin", "obj", "build", "target", "node_modules"}
MAX_WARNINGS = 12


class ProjectError(Exception):
    """프로젝트 파일을 읽을 수 없음."""


@dataclass
class Node:
    name: str
    kind: str                          # "project" | "group" | "file"
    path: Optional[Path] = None        # 실제 파일 (kind == "file")
    children: List["Node"] = field(default_factory=list)
    rel: str = ""                      # 수집 결과와 잇는 파일 식별자

    def group(self, parts: Iterable[str]) -> "Node":
        """이름 경로를 따라 내려가며 없는 묶음은 만든다."""
        node = self
        for part in parts:
            if not part or part == ".":
                continue
            found = next((c for c in node.children if c.kind == "group" and c.name == part), None)
            if found is None:
                found = Node(part, "group")
                node.children.append(found)
            node = found
        return node

    def add_file(self, path: Path, name: Optional[str] = None) -> None:
        path = Path(os.path.abspath(path))
        if not any(c.kind == "file" and c.path == path for c in self.children):
            self.children.append(Node(name or path.name, "file", path))

    def files(self) -> Iterator["Node"]:
        for c in self.children:
            if c.kind == "file":
                yield c
            else:
                yield from c.files()

    def sort(self) -> None:
        self.children.sort(key=lambda c: (c.kind == "file", c.name.lower()))
        for c in self.children:
            c.sort()

    def prune(self) -> None:
        for c in self.children:
            c.prune()
        self.children = [c for c in self.children if c.kind == "file" or c.children]


@dataclass
class Project:
    name: str
    label: str                 # 프로젝트 종류
    origin: Path               # 읽은 프로젝트 파일 또는 폴더
    base: Path                 # 상대 경로의 기준 폴더
    root: Node = field(default_factory=lambda: Node("", "project"))
    warnings: List[str] = field(default_factory=list)
    view_paths: bool = False   # 파일 식별자를 개발도구에서 보이는 경로(트리의 위치)로 삼는다

    def __post_init__(self) -> None:
        self.root.name = self.name

    def warn(self, message: str) -> None:
        if len(self.warnings) < MAX_WARNINGS:
            self.warnings.append(message)
        elif len(self.warnings) == MAX_WARNINGS:
            self.warnings.append("… (이하 생략)")

    def place(self, path: Path, base: Optional[Path] = None, under: Optional[Node] = None) -> None:
        """파일을 기준 폴더에서 본 폴더 구조대로 넣는다."""
        if language_for(path.name) is None:
            return
        rel = _relative(path, base or self.base).split("/")
        (under or self.root).group(rel[:-1]).add_file(path)


# ------------------------------------------------------------------ 공통 도구
def _relative(path: Path, base: Path) -> str:
    """기준 폴더에서 본 경로('/' 구분). 드라이브가 다르면 절대 경로를 쓴다."""
    try:
        return os.path.relpath(path, base).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/").replace(":", "")


def _walk(directory: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if language_for(name) is not None:
                yield Path(dirpath) / name


def _xml(path: Path) -> ET.Element:
    try:
        data = path.read_bytes()
    except OSError as e:
        raise ProjectError(f"{path.name}: 읽을 수 없습니다 ({e.strerror})")
    if b"<!ENTITY" in data:
        raise ProjectError(f"{path.name}: 엔티티 선언이 있는 XML 은 읽지 않습니다")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise ProjectError(f"{path.name}: XML 형식이 올바르지 않습니다 ({e})")
    for el in root.iter():                      # 이름공간을 떼어 낸다
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.rsplit("}", 1)[1]
    return root


def _text(el: Optional[ET.Element], tag: str, default: str = "") -> str:
    found = el.find(tag) if el is not None else None
    return (found.text or "").strip() if found is not None else default


def _win(path: str) -> str:
    return path.replace("\\", "/")


def _read(path: Path) -> str:
    data = path.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


# ------------------------------------------------------------------ 폴더, 낱개 파일
def load_folder(directory: Path, excludes: Iterable[str] = ()) -> Project:
    directory = Path(os.path.abspath(directory))
    proj = Project(directory.name or str(directory), "폴더", directory, directory)
    for path, _rel, _lang in iter_sources([directory], excludes):
        proj.place(path)
    return proj


def load_files(files: List[Path]) -> Project:
    files = [Path(os.path.abspath(f)) for f in files]
    try:
        base = Path(os.path.commonpath([str(f.parent) for f in files]))
    except ValueError:                      # 드라이브가 서로 다름
        base = files[0].parent
    proj = Project("선택한 파일", "소스 파일", base, base)
    for f in files:
        proj.place(f)
    return proj


# ------------------------------------------------------------------ Visual Studio
def _msbuild_items(path: Path) -> List[Tuple[str, str, Dict[str, str]]]:
    """(항목 종류, Include 값, 하위 요소) 목록."""
    items = []
    for el in _xml(path).iter():
        for attr in ("Include", "Remove"):
            if attr in el.attrib:
                items.append((el.tag if attr == "Include" else el.tag + ".Remove", el.attrib[attr],
                              {c.tag: (c.text or "").strip() for c in el}))
    return items


def _msbuild_paths(include: str, base: Path, proj: Project, solution_dir: Optional[Path]) -> List[Path]:
    out: List[Path] = []
    for one in include.split(";"):
        one = urllib.parse.unquote(one.strip())
        if not one:
            continue
        for macro, value in (("ProjectDir", base), ("MSBuildProjectDirectory", base),
                             ("MSBuildThisFileDirectory", base), ("SolutionDir", solution_dir or base)):
            one = re.sub(r"\$\(%s\)[\\/]?" % macro, lambda m: str(value) + os.sep, one)
        if "$(" in one or "%(" in one or "@(" in one:
            proj.warn(f"매크로를 풀 수 없어 건너뜀: {one}")
            continue
        full = os.path.join(base, _win(one))
        if any(ch in one for ch in "*?"):
            out += [Path(p) for p in sorted(glob.glob(full, recursive=True)) if os.path.isfile(p)]
        else:
            out.append(Path(full))
    return out


def load_vcxproj(path: Path, solution_dir: Optional[Path] = None, name: Optional[str] = None) -> Project:
    path = Path(os.path.abspath(path))
    proj = Project(name or path.stem, "Visual Studio C/C++ 프로젝트", path, path.parent, view_paths=True)
    filters: Dict[str, str] = {}
    filter_file = path.with_name(path.name + ".filters")
    if filter_file.is_file():
        for _tag, include, sub in _msbuild_items(filter_file):
            if "Filter" in sub:
                filters[_win(include).lower()] = sub["Filter"]
    for tag, include, _sub in _msbuild_items(path):
        if tag not in ("ClCompile", "ClInclude"):
            continue
        for src in _msbuild_paths(include, proj.base, proj, solution_dir):
            if language_for(src.name) is None:
                continue
            if not src.is_file():
                proj.warn(f"파일이 없음: {include}")
                continue
            if filter_file.is_file():       # 솔루션 탐색기의 필터(가상 폴더) 구조를 따른다
                proj.root.group(_win(filters.get(_win(include).lower(), "")).split("/")).add_file(src)
            else:
                proj.place(src)
    return proj


def load_csproj(path: Path, solution_dir: Optional[Path] = None, name: Optional[str] = None) -> Project:
    path = Path(os.path.abspath(path))
    proj = Project(name or path.stem, "Visual Studio C# 프로젝트", path, path.parent, view_paths=True)
    root = _xml(path)
    items = _msbuild_items(path)
    files: Dict[Path, Optional[str]] = {}
    if "Sdk" in root.attrib or any(el.tag == "Import" and "Sdk" in el.attrib for el in root.iter()):
        # SDK 형식: 프로젝트 폴더 아래의 *.cs 가 자동으로 포함된다 (bin, obj 제외)
        for src in _walk(proj.base):
            parts = {p.lower() for p in src.relative_to(proj.base).parts[:-1]}
            if src.suffix.lower() == ".cs" and not parts & {"bin", "obj"}:
                files[src] = None
    for tag, include, sub in items:
        if tag == "Compile":
            for src in _msbuild_paths(include, proj.base, proj, solution_dir):
                if src.is_file():
                    files[Path(os.path.abspath(src))] = sub.get("Link")
                else:
                    proj.warn(f"파일이 없음: {include}")
    for tag, include, _sub in items:
        if tag == "Compile.Remove":
            for src in _msbuild_paths(include, proj.base, proj, solution_dir):
                files.pop(Path(os.path.abspath(src)), None)
    for src, link in files.items():
        if link:
            parts = _win(link).split("/")
            proj.root.group(parts[:-1]).add_file(src, parts[-1])
        else:
            proj.place(src)
    return proj


def load_atmel(path: Path, solution_dir: Optional[Path] = None, name: Optional[str] = None) -> Project:
    """Microchip(Atmel) Studio 프로젝트. MSBuild 형식이며 소스와 헤더가 모두 Compile 항목이다."""
    path = Path(os.path.abspath(path))
    device = next((el.text or "" for el in _xml(path).iter("avrdevice")), "").strip()
    label = "Microchip(Atmel) Studio 프로젝트" + (f" ({device})" if device else "")
    proj = Project(name or path.stem, label, path, path.parent, view_paths=True)
    for tag, include, sub in _msbuild_items(path):
        if tag != "Compile":
            continue
        for src in _msbuild_paths(include, proj.base, proj, solution_dir):
            if language_for(src.name) is None:
                continue
            if not src.is_file():
                proj.warn(f"파일이 없음: {include}")
            elif sub.get("Link"):                   # 프로젝트 폴더 밖의 파일을 연결한 항목
                parts = _win(sub["Link"]).split("/")
                proj.root.group(parts[:-1]).add_file(src, parts[-1])
            else:
                proj.place(src)
    return proj


def load_sln(path: Path) -> List[Project]:
    path = Path(os.path.abspath(path))
    projects: List[Project] = []
    skipped: List[str] = []
    for m in re.finditer(r'^Project\("\{[^}]+\}"\)\s*=\s*"([^"]+)",\s*"([^"]+)"', _read(path), re.M):
        name, rel = m.group(1), _win(m.group(2))
        target = path.parent / rel
        suffix = target.suffix.lower()
        if suffix == ".vcxproj" and target.is_file():
            projects.append(load_vcxproj(target, path.parent, name))
        elif suffix == ".csproj" and target.is_file():
            projects.append(load_csproj(target, path.parent, name))
        elif suffix in (".cproj", ".cppproj") and target.is_file():
            projects.append(load_atmel(target, path.parent, name))
        elif suffix:
            skipped.append(rel)
    if not projects:
        raise ProjectError(f"{path.name}: 읽을 수 있는 프로젝트(.vcxproj, .csproj, .cproj, .cppproj)가 없습니다")
    for rel in skipped:
        projects[0].warn(f"솔루션의 다른 프로젝트는 읽지 않음: {rel}")
    return projects


# ------------------------------------------------------------------ Eclipse 계열
_VIRTUAL = Path("virtual:/virtual")     # 위치가 없는 가상 폴더


def _eclipse_resolve(uri: str, base: Path, variables: Dict[str, str], depth: int = 0) -> Optional[Path]:
    """연결된 리소스의 위치를 푼다. `.project` 의 경로 변수(variableList)와 PARENT-n-, PROJECT_LOC 을 안다."""
    uri = re.sub(r"\$\{([^}]+)\}", r"\1", urllib.parse.unquote(uri.strip()))
    if not uri or depth > 10:
        return None
    if uri.startswith("virtual:"):
        return _VIRTUAL
    if uri.startswith("file:"):
        return Path(urllib.request.url2pathname(urllib.parse.urlsplit(uri).path))
    head, _, rest = uri.replace("\\", "/").partition("/")
    m = re.match(r"PARENT-(\d+)-(.+)$", head)
    name = m.group(2) if m else head
    if name == "PROJECT_LOC":
        root: Optional[Path] = base
    elif name == "WORKSPACE_LOC":
        root = base.parent
    elif name in variables:
        root = _eclipse_resolve(variables[name], base, variables, depth + 1)
    elif re.match(r"[A-Za-z]:$", head) or uri.startswith("/"):
        return Path(uri)
    else:
        root = None
    if root is None or root == _VIRTUAL:
        return None
    for _ in range(int(m.group(1)) if m else 0):
        root = root.parent
    return root / rest if rest else root


def _eclipse_location(link: ET.Element, base: Path, variables: Dict[str, str]) -> Optional[Path]:
    location = _text(link, "location")
    if location:
        return Path(location)
    return _eclipse_resolve(_text(link, "locationURI"), base, variables)


def _excluded(rel: str, patterns: List[str]) -> bool:
    for pat in patterns:
        pat = pat.strip("/")
        if rel == pat or rel.startswith(pat + "/") or fnmatch.fnmatch(rel, pat):
            return True
    return False


# 리소스 필터의 종류(type)는 비트 합이다
_F_INCLUDE, _F_EXCLUDE, _F_FILES, _F_FOLDERS, _F_INHERIT = 1, 2, 4, 8, 16


def _eclipse_matcher(matcher: Optional[ET.Element], proj: Project):
    """리소스 필터의 조건을 (이름, 프로젝트 기준 경로) -> bool 함수로 만든다. 모르는 조건이면 None."""
    if matcher is None:
        return None
    kind = _text(matcher, "id")
    args = matcher.find("arguments")
    text = (args.text or "").strip() if args is not None else ""
    nested = [_eclipse_matcher(m, proj) for m in (args.findall("matcher") if args is not None else [])]
    if kind.endswith(("orFilterMatcher", "andFilterMatcher", "notFilterMatcher")):
        if not nested or None in nested:
            return None
        if kind.endswith("orFilterMatcher"):
            return lambda name, rel: any(f(name, rel) for f in nested)
        if kind.endswith("andFilterMatcher"):
            return lambda name, rel: all(f(name, rel) for f in nested)
        return lambda name, rel: not nested[0](name, rel)
    if kind.endswith("regexFilterMatcher"):
        try:
            regex = re.compile(text)
        except re.error:
            return None
        return lambda name, rel: regex.fullmatch(name) is not None
    if kind.endswith("patternFilterMatcher"):          # 예전 형식: 인자가 곧 이름 패턴
        return lambda name, rel: fnmatch.fnmatchcase(name, text)
    if kind.endswith("multiFilter"):                   # "1.0-name-matches-false-false-패턴"
        parts = text.split("-", 5)
        if len(parts) == 6 and parts[1] in ("name", "projectRelativePath") and parts[2] in ("matches", "equals"):
            _ver, key, op, case, is_regex, arg = parts
            fold = (lambda s: s) if case == "true" else (lambda s: s.lower())
            if op == "matches" and is_regex == "true":
                try:
                    regex = re.compile(arg, 0 if case == "true" else re.I)
                except re.error:
                    return None
                test = lambda s: regex.fullmatch(s) is not None       # noqa: E731
            elif op == "matches":
                test = lambda s: fnmatch.fnmatchcase(fold(s), fold(arg))   # noqa: E731
            else:
                test = lambda s: fold(s) == fold(arg)                 # noqa: E731
            return (lambda name, rel: test(name)) if key == "name" else (lambda name, rel: test(rel))
    return None


def _eclipse_filters(description: Optional[ET.Element], proj: Project) -> Dict[str, List[Tuple[int, object]]]:
    """`.project` 의 리소스 필터. 폴더(프로젝트 기준 경로)마다 그 안에서 보일 파일·폴더를 정한다."""
    filters: Dict[str, List[Tuple[int, object]]] = {}
    for el in (description.iter("filter") if description is not None else []):
        try:
            kind = int(_text(el, "type", "0"))
        except ValueError:
            continue
        test = _eclipse_matcher(el.find("matcher"), proj)
        folder = _text(el, "name").strip("/")
        if test is None:
            proj.warn(f"리소스 필터를 해석하지 못해 건너뜀: {folder or '(프로젝트)'}")
            continue
        filters.setdefault(folder, []).append((kind, test))
    return filters


def load_eclipse(directory: Path) -> Project:
    directory = Path(os.path.abspath(directory))
    if (directory / ".ccsproject").is_file():
        label = "Code Composer Studio 프로젝트"
    elif (directory / ".wrproject").is_file():
        label = "Wind River Workbench 프로젝트"
    elif (directory / ".cproject").is_file():
        xilinx = b"xilinx" in (directory / ".cproject").read_bytes().lower()
        label = "Xilinx SDK/Vitis 프로젝트" if xilinx else "Eclipse CDT 프로젝트"
    elif (directory / ".classpath").is_file():
        label = "Eclipse Java 프로젝트"
    else:
        label = "Eclipse 프로젝트"
    description = _xml(directory / ".project") if (directory / ".project").is_file() else None
    proj = Project(_text(description, "name", directory.name), label, directory, directory, view_paths=True)

    roots: List[str] = []           # 소스 폴더 (비어 있으면 프로젝트 전체)
    excluded: List[str] = []
    if (directory / ".cproject").is_file():
        entries = _xml(directory / ".cproject").find(".//sourceEntries")   # 소스 폴더를 정한 첫 번째 빌드 구성
        for entry in entries if entries is not None else []:
            if entry.get("kind") != "sourcePath":
                continue
            name = entry.get("name", "").strip("/")
            if name:
                roots.append(name)
            excluded += [f"{name}/{p}".strip("/") for p in entry.get("excluding", "").split("|") if p]
    if (directory / ".classpath").is_file():
        for entry in _xml(directory / ".classpath").iter("classpathentry"):
            if entry.get("kind") == "src" and not entry.get("path", "/").startswith("/"):
                roots.append(entry.get("path", "").strip("/"))
                excluded += [f"{roots[-1]}/{p}" for p in entry.get("excluding", "").split("|") if p]
    roots = sorted(set(roots))
    for sub in roots:
        if not (directory / sub).is_dir():
            proj.warn(f"소스 폴더가 없음: {sub}")

    variables = {_text(v, "name"): _text(v, "value") for v in
                 (description.iter("variable") if description is not None else [])}
    filters = _eclipse_filters(description, proj)

    def visible(name: str, rel: str, is_dir: bool, inherited: List[Tuple[int, object]]) -> bool:
        """리소스 필터: 포함 필터가 있으면 그중 하나에 맞아야 하고, 제외 필터에 맞으면 안 된다."""
        parent = rel.rpartition("/")[0]
        active = [f for f in filters.get(parent, []) + inherited
                  if f[0] & (_F_FOLDERS if is_dir else _F_FILES)]
        includes = [test for kind, test in active if kind & _F_INCLUDE]
        if includes and not any(test(name, rel) for test in includes):
            return False
        return not any(test(name, rel) for kind, test in active if kind & _F_EXCLUDE)

    def in_roots(rel: str, is_dir: bool) -> bool:
        if not roots:
            return True
        return any(rel == r or rel.startswith(r + "/") or (is_dir and r.startswith(rel + "/")) for r in roots)

    def walk(real: Path, virtual: str, inherited: List[Tuple[int, object]], linked: bool) -> None:
        """실제 폴더 real 을 프로젝트 안의 경로 virtual 로 보고 훑는다."""
        try:
            children = sorted(os.scandir(real), key=lambda e: e.name.lower())
        except OSError:
            return
        below = inherited + [f for f in filters.get(virtual, []) if f[0] & _F_INHERIT]
        for child in children:
            rel = f"{virtual}/{child.name}".strip("/")
            is_dir = child.is_dir()
            if child.name.startswith(".") or not visible(child.name, rel, is_dir, inherited):
                continue
            if _excluded(rel, excluded) or not (linked or in_roots(rel, is_dir)):
                continue
            if is_dir:
                walk(Path(child.path), rel, below, linked)
            elif language_for(child.name) is not None:
                proj.root.group(rel.split("/")[:-1]).add_file(Path(child.path))

    walk(directory, "", [], False)

    for link in (description.iter("link") if description is not None else []):   # 연결된 리소스
        name = _text(link, "name").strip("/")
        target = _eclipse_location(link, directory, variables)
        if target == _VIRTUAL:
            continue
        if target is None:
            proj.warn(f"연결된 리소스의 위치를 풀 수 없음: {name}")
        elif target.is_dir():
            if visible(name.rpartition("/")[2], name, True, []):
                walk(target, name, [], True)
        elif target.is_file():
            if language_for(target.name) and visible(name.rpartition("/")[2], name, False, []) \
                    and not _excluded(name, excluded):
                parts = name.split("/")
                proj.root.group(parts[:-1]).add_file(target, parts[-1])
        else:
            proj.warn(f"연결된 리소스가 없음: {name} -> {target}")
    return proj


# ------------------------------------------------------------------ Makefile
_MAKE_ASSIGN = re.compile(r"(?:(?:export|override|private)\s+)*([A-Za-z0-9_.\-/]+)\s*(\+=|::=|:=|\?=|!=|=)\s*(.*)")
_MAKE_SKIP = re.compile(r"(?:ifeq|ifneq|ifdef|ifndef|else|endif|define|endef|export|unexport|\.PHONY|\.SUFFIXES)\b")


def _pattern_subst(word: str, pattern: str, replacement: str) -> str:
    if "%" not in pattern:
        return replacement if word == pattern else word
    head, tail = pattern.split("%", 1)
    if word.startswith(head) and word.endswith(tail) and len(word) >= len(head) + len(tail):
        return replacement.replace("%", word[len(head):len(word) - len(tail)], 1)
    return word


class _Makefile:
    def __init__(self, proj: Project, directory: Path):
        self.proj = proj
        self.dir = directory
        self.vars: Dict[str, str] = {"CURDIR": str(directory), "PWD": str(directory), "MAKE": "make"}
        self.values: List[str] = []       # 대입된 모든 값 (조건문의 양쪽 분기를 모두 본다)
        self.prereqs: List[str] = []
        self.recipes: List[str] = []
        self.vpath: List[str] = []
        self.unsupported: set = set()

    # ---- 읽기 ----
    def parse(self, path: Path, depth: int = 0) -> None:
        text = re.sub(r"\\\r?\n[ \t]*", " ", _read(path))
        for raw in text.split("\n"):
            if raw.startswith("\t"):
                self.recipes.append(raw)
                continue
            line = re.sub(r"(?<!\\)#.*", "", raw).strip()
            if not line:
                continue
            m = re.match(r"(-?include|sinclude)\s+(.*)", line)
            if m:
                for word in self.expand(m.group(2)).split():
                    for inc in sorted(glob.glob(os.path.join(self.dir, word))) or [os.path.join(self.dir, word)]:
                        if os.path.isfile(inc) and depth < 8:
                            self.parse(Path(inc), depth + 1)
                continue
            m = re.match(r"vpath\s+\S+\s+(.*)", line)
            if m:
                self.vpath += re.split(r"[\s:;]+", self.expand(m.group(1)))
                continue
            m = _MAKE_ASSIGN.match(line)
            if m:
                name, op, value = m.groups()
                if op == "!=":
                    continue
                self.values.append(value)
                if op == "+=":
                    self.vars[name] = (self.vars.get(name, "") + " " + value).strip()
                elif op != "?=" or name not in self.vars:
                    self.vars[name] = value
                continue
            if _MAKE_SKIP.match(line):
                continue
            if ":" in line:
                self.prereqs.append(line.split(":", 1)[1].lstrip(":").split(";", 1)[0].replace("|", " "))

    # ---- 변수/함수 전개 ----
    def expand(self, text: str, depth: int = 0) -> str:
        if "$" not in text or depth > 30:
            return text
        out: List[str] = []
        i = 0
        while i < len(text):
            ch = text[i]
            if ch != "$" or i + 1 >= len(text):
                out.append(ch)
                i += 1
                continue
            nxt = text[i + 1]
            if nxt == "$":
                out.append("$")
                i += 2
            elif nxt in "({":
                close = {"(": ")", "{": "}"}[nxt]
                level, j = 1, i + 2
                while j < len(text) and level:
                    level += text[j] == nxt
                    level -= text[j] == close
                    j += 1
                out.append(self.reference(text[i + 2:j - 1], depth))
                i = j
            else:
                out.append(self.expand(self.vars.get(nxt, ""), depth + 1) if nxt.isalnum() else "")
                i += 2
        return "".join(out)

    def reference(self, inner: str, depth: int) -> str:
        m = re.match(r"([a-z\-]+)\s+(.*)", inner, re.S)
        if m and m.group(1) in _MAKE_FUNCS:
            return self.call(m.group(1), m.group(2), depth)
        m = re.match(r"([^:=\s]+):([^=]*)=(.*)", inner, re.S)       # $(VAR:.c=.o)
        if m:
            pattern, repl = self.expand(m.group(2), depth + 1), self.expand(m.group(3), depth + 1)
            if "%" not in pattern:
                pattern, repl = "%" + pattern, "%" + repl
            words = self.expand(self.vars.get(self.expand(m.group(1), depth + 1), ""), depth + 1).split()
            return " ".join(_pattern_subst(w, pattern, repl) for w in words)
        return self.expand(self.vars.get(self.expand(inner.strip(), depth + 1), ""), depth + 1)

    def call(self, name: str, rest: str, depth: int) -> str:
        args: List[str] = []
        level, start = 0, 0
        for i, ch in enumerate(rest):
            level += ch in "({"
            level -= ch in ")}"
            if ch == "," and level == 0:
                args.append(rest[start:i])
                start = i + 1
        args.append(rest[start:])
        if name == "foreach" and len(args) >= 3:
            saved = self.vars.get(args[0].strip())
            parts = []
            for word in self.expand(args[1], depth + 1).split():
                self.vars[args[0].strip()] = word
                parts.append(self.expand(",".join(args[2:]), depth + 1))
            if saved is None:
                self.vars.pop(args[0].strip(), None)
            else:
                self.vars[args[0].strip()] = saved
            return " ".join(parts)
        a = [self.expand(x, depth + 1) for x in args]
        words = a[-1].split()
        if name == "wildcard":
            found: List[str] = []
            for pat in words:
                for hit in sorted(glob.glob(os.path.join(self.dir, pat))):
                    found.append(hit if os.path.isabs(pat) else os.path.relpath(hit, self.dir).replace("\\", "/"))
            return " ".join(found)
        if name == "patsubst" and len(a) >= 3:
            return " ".join(_pattern_subst(w, a[0].strip(), a[1].strip()) for w in words)
        if name == "subst" and len(a) >= 3:
            return a[2].replace(a[0], a[1])
        if name == "addprefix" and len(a) >= 2:
            return " ".join(a[0].strip() + w for w in words)
        if name == "addsuffix" and len(a) >= 2:
            return " ".join(w + a[0].strip() for w in words)
        if name in ("filter", "filter-out") and len(a) >= 2:
            pats = a[0].split()
            hit = lambda w: any(_pattern_subst(w, p, "\0") == "\0" for p in pats)   # noqa: E731
            return " ".join(w for w in words if hit(w) == (name == "filter"))
        if name == "notdir":
            return " ".join(w.replace("\\", "/").rsplit("/", 1)[-1] for w in words)
        if name == "dir":
            return " ".join(w.rsplit("/", 1)[0] + "/" if "/" in w else "./" for w in words)
        if name == "basename":
            return " ".join(os.path.splitext(w)[0] for w in words)
        if name == "sort":
            return " ".join(sorted(set(words)))
        if name in ("strip", "abspath", "realpath", "firstword", "lastword", "if", "or", "and", "join"):
            return " ".join(" ".join(a).split())      # 넉넉하게: 인자에 든 낱말을 모두 후보로 둔다
        self.unsupported.add(name)
        return ""

    # ---- 소스 찾기 ----
    def sources(self) -> List[Path]:
        words: List[str] = []
        for value in self.values + self.prereqs:
            words += self.expand(value).replace('"', " ").replace("'", " ").split()
        search = [self.dir]
        for d in re.split(r"[\s:;]+", self.expand(self.vars.get("VPATH", ""))) + self.vpath:
            if d and (self.dir / d).is_dir():
                search.append(self.dir / d)
        found: Dict[Path, None] = {}
        objects: List[str] = []
        for word in words:
            suffix = os.path.splitext(word)[1].lower()
            if suffix in SOURCE_EXTS:
                hit = next((d / word for d in search if (d / word).is_file()), None)
                if hit is not None:
                    found[Path(os.path.abspath(hit))] = None
                elif "%" not in word and "*" not in word:
                    self.proj.warn(f"파일이 없음: {word}")
            elif suffix in (".o", ".obj", ".lo"):
                objects.append(os.path.splitext(word)[0])
            elif not suffix and re.fullmatch(r"[\w./\-]+", word):
                objects.append(word)        # 암묵 규칙: 확장자 없는 대상 prog 는 prog.c 에서 만든다
        # 오브젝트 이름(foo.o)만 있는 경우: 같은 이름의 소스를 찾는다
        search += [p for p in dict.fromkeys(f.parent for f in found) if p not in search]
        for stem in dict.fromkeys(objects):
            names = [stem, stem.replace("\\", "/").rsplit("/", 1)[-1]]
            for name in names:
                hits = [d / (name + ext) for d in search for ext in SOURCE_EXTS if (d / (name + ext)).is_file()]
                if hits:
                    found[Path(os.path.abspath(hits[0]))] = None
                    break
        return list(found)

    def subdirs(self) -> List[Path]:
        names: List[str] = []
        for var in ("SUBDIRS", "SUBDIR", "DIRS"):
            names += self.expand(self.vars.get(var, "")).split()
        for recipe in self.recipes:
            line = self.expand(recipe)
            names += re.findall(r"-C\s*(\S+)", line) + re.findall(r"\bcd\s+(\S+)\s*(?:&&|;)\s*(?:make|\$)", line)
        return [self.dir / n for n in dict.fromkeys(names) if (self.dir / n).is_dir()]


_MAKE_FUNCS = {"wildcard", "patsubst", "subst", "addprefix", "addsuffix", "filter", "filter-out", "notdir", "dir",
               "basename", "sort", "strip", "abspath", "realpath", "firstword", "lastword", "if", "or", "and",
               "join", "foreach", "shell", "call", "eval", "origin", "value", "error", "warning", "info", "suffix",
               "word", "wordlist", "words", "flavor", "file"}


def _makefile_in(directory: Path) -> Optional[Path]:
    for name in ("GNUmakefile", "makefile", "Makefile"):
        if (directory / name).is_file():
            return directory / name
    return None


def load_makefile(path: Path) -> Project:
    path = Path(os.path.abspath(path))
    title = path.parent.name if path.name.lower() in MAKEFILE_NAMES else f"{path.parent.name} ({path.name})"
    proj = Project(title, "Makefile", path, path.parent)
    seen: set = set()
    unsupported: set = set()

    def visit(makefile: Path, depth: int) -> None:
        if makefile in seen or depth > 6:
            return
        seen.add(makefile)
        mk = _Makefile(proj, makefile.parent)
        mk.parse(makefile)
        for src in mk.sources():
            proj.place(src)
        unsupported.update(mk.unsupported)
        for sub in mk.subdirs():
            child = _makefile_in(sub)
            if child is not None:
                visit(child, depth + 1)

    visit(path, 0)
    if unsupported & {"shell", "call", "eval"}:
        proj.warn("$(shell), $(call), $(eval) 로 정해지는 값은 해석하지 않았습니다: 소스가 빠졌을 수 있습니다")
    if not any(proj.root.files()):
        proj.warn("makefile 에서 소스 목록을 찾지 못해 폴더 전체를 표시합니다")
        for src in _walk(proj.base):
            proj.place(src)
    return proj


# ------------------------------------------------------------------ CMake
_CMAKE_KEYWORDS = {"WIN32", "MACOSX_BUNDLE", "EXCLUDE_FROM_ALL", "STATIC", "SHARED", "MODULE", "OBJECT", "INTERFACE",
                   "PRIVATE", "PUBLIC", "IMPORTED", "GLOBAL", "ALIAS", "UNKNOWN"}


def _cmake_commands(text: str) -> Iterator[Tuple[str, List[str]]]:
    text = re.sub(r"#\[\[.*?\]\]", "", text, flags=re.S)
    text = re.sub(r'("(?:\\.|[^"\\])*")|#[^\n]*', lambda m: m.group(1) or "", text)
    pos = 0
    while True:
        m = re.compile(r"([A-Za-z_]\w*)\s*\(").search(text, pos)
        if not m:
            return
        level, i = 1, m.end()
        in_quote = False
        while i < len(text) and level:
            ch = text[i]
            if ch == "\\":
                i += 1
            elif ch == '"':
                in_quote = not in_quote
            elif not in_quote:
                level += ch == "("
                level -= ch == ")"
            i += 1
        args = [a[1:-1] if a.startswith('"') else a
                for a in re.findall(r'"(?:\\.|[^"\\])*"|[^\s;()"]+', text[m.end():i - 1])]
        yield m.group(1).lower(), args
        pos = i


class _CMake:
    def __init__(self, proj: Project, top: Path):
        self.proj = proj
        self.top = top
        self.targets: Dict[str, Dict[Path, None]] = {}

    def expand(self, text: str, variables: Dict[str, str]) -> str:
        for _ in range(20):
            new = re.sub(r"\$\{([^${}]+)\}", lambda m: variables.get(m.group(1), ""), text)
            if new == text:
                break
            text = new
        return text

    def run(self, path: Path, variables: Dict[str, str], depth: int = 0) -> None:
        cur = path.parent
        variables = dict(variables, CMAKE_CURRENT_SOURCE_DIR=cur.as_posix(), CMAKE_CURRENT_LIST_DIR=cur.as_posix())
        for name, raw in _cmake_commands(_read(path)):
            args: List[str] = []
            for a in raw:
                if "$<" not in a:
                    args += [x for x in self.expand(a, variables).split(";") if x]
            if not args:
                continue
            if name == "project":
                variables["PROJECT_NAME"] = args[0]
                variables["PROJECT_SOURCE_DIR"] = cur.as_posix()
                if depth == 0:
                    self.proj.name = self.proj.root.name = args[0]
            elif name == "set":
                values = []
                for a in args[1:]:
                    if a in ("CACHE", "PARENT_SCOPE"):
                        break
                    values.append(a)
                variables[args[0]] = ";".join(values)
            elif name == "list" and len(args) >= 2 and args[0] == "APPEND":
                variables[args[1]] = ";".join(filter(None, [variables.get(args[1], "")] + args[2:]))
            elif name == "file" and args[0] in ("GLOB", "GLOB_RECURSE") and len(args) >= 2:
                hits: List[str] = []
                skip = False
                for a in args[2:]:
                    if skip or a in ("CONFIGURE_DEPENDS", "FOLLOW_SYMLINKS"):
                        skip = False
                    elif a in ("LIST_DIRECTORIES", "RELATIVE"):
                        skip = True
                    else:
                        full = a if os.path.isabs(a) else os.path.join(cur, a)
                        if args[0] == "GLOB_RECURSE":
                            head, tail = os.path.split(full)
                            full = os.path.join(head, "**", tail)
                        hits += sorted(glob.glob(full, recursive=True))
                variables[args[1]] = ";".join(h.replace("\\", "/") for h in hits)
            elif name == "aux_source_directory" and len(args) >= 2:
                folder = cur / args[0]
                hits = [p.as_posix() for p in sorted(folder.glob("*")) if p.suffix.lower() in SOURCE_EXTS]
                variables[args[1]] = ";".join(filter(None, [variables.get(args[1], "")] + hits))
            elif name in ("add_executable", "add_library", "target_sources"):
                # 대상 이름이 사용자 함수가 정한 변수이면 풀리지 않는다: 쓴 그대로 보여 준다
                first = self.expand(raw[0], variables)
                sources = args[1:] if first else args
                target = self.targets.setdefault(first or raw[0], {})
                for a in sources:
                    if a in _CMAKE_KEYWORDS or os.path.splitext(a)[1].lower() not in SOURCE_EXTS:
                        continue
                    src = Path(a) if os.path.isabs(a) else cur / a
                    if src.is_file():
                        target[Path(os.path.abspath(src))] = None
                    else:
                        self.proj.warn(f"파일이 없음: {a}")
            elif name == "add_subdirectory":
                child = (cur / args[0]) / "CMakeLists.txt"
                if child.is_file() and depth < 10:
                    self.run(child, variables, depth + 1)
            elif name == "include" and args[0].endswith(".cmake"):
                inc = Path(args[0]) if os.path.isabs(args[0]) else cur / args[0]
                if inc.is_file() and depth < 10:
                    self.run(inc, variables, depth + 1)


def load_cmake(path: Path) -> Project:
    path = Path(os.path.abspath(path))
    proj = Project(path.parent.name, "CMake", path, path.parent)
    cm = _CMake(proj, path.parent)
    cm.run(path, {"CMAKE_SOURCE_DIR": path.parent.as_posix(), "PROJECT_SOURCE_DIR": path.parent.as_posix()})
    for target, files in cm.targets.items():
        for src in files:
            proj.place(src, under=proj.root.group([target]))
    if not any(proj.root.files()):
        proj.warn("CMakeLists.txt 에서 소스 목록을 찾지 못해 폴더 전체를 표시합니다")
        for src in _walk(proj.base):
            proj.place(src)
    return proj


# ------------------------------------------------------------------ IAR, Keil
def load_iar(path: Path) -> Project:
    path = Path(os.path.abspath(path))
    proj = Project(path.stem, "IAR Embedded Workbench 프로젝트", path, path.parent, view_paths=True)

    def visit(el: ET.Element, node: Node) -> None:
        for child in el:
            if child.tag == "group":
                visit(child, node.group([_text(child, "name", "group")]))
            elif child.tag == "file":
                name = _text(child, "name")
                src = Path(_win(name.replace("$PROJ_DIR$", str(path.parent))))
                if language_for(src.name) is None:
                    continue
                if src.is_file():
                    node.add_file(src)
                else:
                    proj.warn(f"파일이 없음: {name}")

    visit(_xml(path), proj.root)
    return proj


def load_iar_workspace(path: Path) -> List[Project]:
    path = Path(os.path.abspath(path))
    projects = []
    for el in _xml(path).iter("path"):
        target = Path(_win((el.text or "").strip().replace("$WS_DIR$", str(path.parent))))
        if target.suffix.lower() == ".ewp" and target.is_file():
            projects.append(load_iar(target))
    if not projects:
        raise ProjectError(f"{path.name}: 읽을 수 있는 프로젝트(.ewp)가 없습니다")
    return projects


def load_keil(path: Path) -> Project:
    path = Path(os.path.abspath(path))
    proj = Project(path.stem, "Keil uVision 프로젝트", path, path.parent, view_paths=True)
    targets = list(_xml(path).iter("Target"))
    for target in targets:
        top = proj.root if len(targets) == 1 else proj.root.group([_text(target, "TargetName", "Target")])
        for grp in target.iter("Group"):
            node = top.group([_text(grp, "GroupName", "Group")])
            for f in grp.iter("File"):
                name = _text(f, "FilePath")
                src = path.parent / _win(name)
                if language_for(src.name) is None:
                    continue
                if src.is_file():
                    node.add_file(src)
                else:
                    proj.warn(f"파일이 없음: {name}")
    return proj


# ------------------------------------------------------------------ Maven, Gradle
def load_maven(path: Path) -> Project:
    path = Path(os.path.abspath(path))
    root = _xml(path)
    proj = Project(_text(root, "artifactId", path.parent.name), "Maven 프로젝트", path, path.parent)

    def visit(pom: Path, depth: int) -> None:
        doc = _xml(pom)
        build = doc.find("build")
        for tag, default in (("sourceDirectory", "src/main/java"), ("testSourceDirectory", "src/test/java")):
            folder = pom.parent / _text(build, tag, default)
            if folder.is_dir():
                for src in _walk(folder):
                    proj.place(src)
        for module in doc.iter("module"):
            child = pom.parent / (module.text or "").strip() / "pom.xml"
            if child.is_file() and depth < 6:
                visit(child, depth + 1)

    visit(path, 0)
    return proj


def load_gradle(path: Path) -> Project:
    directory = Path(os.path.abspath(path)).parent
    proj = Project(directory.name, "Gradle 프로젝트", Path(os.path.abspath(path)), directory)
    folders = [directory]
    for name in ("settings.gradle", "settings.gradle.kts"):
        if (directory / name).is_file():
            text = re.sub(r"//[^\n]*", "", _read(directory / name))
            for line in re.findall(r"^\s*include\b(.*)$", text, re.M):
                folders += [directory / n.strip(":").replace(":", "/") for n in re.findall(r"""['"]([^'"]+)['"]""", line)]
    found = False
    for folder in folders:
        for sub in ("src/main/java", "src/test/java", "src/main/cpp", "src/main/c"):
            if (folder / sub).is_dir():
                found = True
                for src in _walk(folder / sub):
                    proj.place(src)
    proj.warn("Gradle 은 관례상의 소스 폴더(src/main/java 등)만 읽습니다" if found
              else "관례상의 소스 폴더(src/main/java 등)를 찾지 못했습니다")
    return proj


# ------------------------------------------------------------------ 진입점
def project_kind(name: str) -> Optional[str]:
    """파일 이름이 읽을 수 있는 프로젝트 파일이면 그 종류를, 아니면 None 을 돌려준다."""
    low = name.lower()
    suffix = os.path.splitext(low)[1]
    if low in ECLIPSE_FILES:
        return "Eclipse 계열 (CCS, Xilinx, CDT, Workbench)"
    if low in MAKEFILE_NAMES or suffix in (".mk", ".mak"):
        return "Makefile"
    if low == "cmakelists.txt":
        return "CMake"
    if low == "pom.xml":
        return "Maven"
    if low in GRADLE_FILES:
        return "Gradle"
    return {".sln": "Visual Studio 솔루션", ".vcxproj": "Visual Studio C/C++", ".csproj": "Visual Studio C#",
            ".atsln": "Microchip(Atmel) Studio 솔루션", ".cproj": "Microchip(Atmel) Studio C",
            ".cppproj": "Microchip(Atmel) Studio C++",
            ".ewp": "IAR 프로젝트", ".eww": "IAR 작업 공간", ".uvprojx": "Keil uVision",
            ".uvproj": "Keil uVision"}.get(suffix)


# 폴더를 열 때 대표로 삼을 프로젝트 파일의 순위 (작을수록 먼저). 솔루션·작업 공간이 그 안의 프로젝트를 모두 담는다.
_RANKS = (
    (".sln", ".atsln", ".eww"),
    (".vcxproj", ".csproj", ".cproj", ".cppproj", ".ewp", ".uvprojx", ".uvproj"),
    ECLIPSE_FILES,
    ("cmakelists.txt",),
    MAKEFILE_NAMES,
    ("pom.xml",),
    GRADLE_FILES,
)


def project_rank(name: str) -> Optional[int]:
    """폴더를 열 때 대표가 될 수 있는 프로젝트 파일이면 순위, 아니면 None.

    `*.mk`, `*.mak` 는 다른 makefile 이 불러 쓰는 조각인 경우가 많아 대표로 삼지 않는다(직접 고르면 열 수 있다).
    """
    low = name.lower()
    for rank, names in enumerate(_RANKS):
        if low in names or os.path.splitext(low)[1] in names:
            return rank
    return None


def detect_projects(directory: Path) -> List[Path]:
    """폴더 바로 아래에 있는 프로젝트 파일 가운데 대표(가장 높은 순위)인 것들. 없으면 빈 목록."""
    try:
        files = [p for p in sorted(Path(directory).iterdir(), key=lambda p: p.name.lower())
                 if p.is_file() and project_rank(p.name) is not None]
    except OSError:
        return []
    if not files:
        return []
    best = min(project_rank(p.name) for p in files)
    chosen = [p for p in files if project_rank(p.name) == best]
    if best == _RANKS.index(ECLIPSE_FILES) or best == _RANKS.index(GRADLE_FILES):
        # 같은 프로젝트를 이루는 파일들이다: 하나만 고른다 (.project, settings.gradle 을 먼저)
        prefer = (".project", "settings.gradle", "settings.gradle.kts")
        chosen = [next((p for p in chosen if p.name.lower() in prefer), chosen[0])]
    return chosen


def resolve_inputs(paths: Iterable[Path], whole_folder: bool = False) -> Tuple[List[Path], List[str]]:
    """폴더를 프로젝트 파일로 바꾼다: 폴더에 프로젝트 파일이 있으면 그것으로, 없으면 폴더 전체(하위 폴더 포함)로.

    반환: (열 대상, 사용자에게 알릴 말). whole_folder 이면 바꾸지 않는다.
    """
    out: List[Path] = []
    notes: List[str] = []
    for path in paths:
        path = Path(path)
        found = detect_projects(path) if path.is_dir() and not whole_folder else []
        if found:
            out += found
            notes.append(f"{path}: 프로젝트 파일 {', '.join(p.name for p in found)} 로 엽니다 "
                         "(폴더의 모든 소스를 보려면 --folder)")
        else:
            out.append(path)
    return out, notes


def load(path: Path, excludes: Iterable[str] = ()) -> List[Project]:
    path = Path(path)
    if path.is_dir():
        return [load_folder(path, excludes)]
    if not path.is_file():
        raise ProjectError(f"경로가 없습니다: {path}")
    low = path.name.lower()
    suffix = path.suffix.lower()
    if low in ECLIPSE_FILES:
        return [load_eclipse(path.parent)]
    if low in MAKEFILE_NAMES or suffix in (".mk", ".mak"):
        return [load_makefile(path)]
    if low == "cmakelists.txt":
        return [load_cmake(path)]
    if low == "pom.xml":
        return [load_maven(path)]
    if low in GRADLE_FILES:
        return [load_gradle(path)]
    loaders = {".sln": load_sln, ".atsln": load_sln, ".eww": load_iar_workspace}
    if suffix in loaders:
        return loaders[suffix](path)
    single = {".vcxproj": load_vcxproj, ".csproj": load_csproj, ".cproj": load_atmel, ".cppproj": load_atmel,
              ".ewp": load_iar,
              ".uvprojx": load_keil, ".uvproj": load_keil}
    if suffix in single:
        return [single[suffix](path)]
    raise ProjectError(f"지원하지 않는 파일입니다: {path.name}")


@dataclass
class Workspace:
    projects: List[Project]

    def entries(self) -> List[Tuple[Path, str, Language]]:
        """수집할 (파일, 식별자, 언어) 목록. 같은 파일은 한 번만 넣는다."""
        seen: Dict[Path, str] = {}
        out = []
        for proj in self.projects:
            for node in proj.root.files():
                if node.path not in seen:
                    seen[node.path] = node.rel
                    out.append((node.path, node.rel, language_for(node.path.name)))
        return out


def open_paths(paths: Iterable[Path], excludes: Iterable[str] = ()) -> Workspace:
    """폴더, 프로젝트 파일, 낱개 소스 파일을 섞어 받아 작업 공간을 만든다."""
    excludes = list(excludes)
    projects: List[Project] = []
    loose: List[Path] = []
    for path in paths:
        path = Path(path)
        if path.is_file() and project_kind(path.name) is None and language_for(path.name) is not None:
            loose.append(path)
        else:
            projects += load(path, excludes)
    if loose:
        projects.append(load_files(loose))

    names: Dict[str, int] = {}
    for proj in projects:                     # 이름이 겹치면 번호를 붙인다
        names[proj.name] = names.get(proj.name, 0) + 1
        if names[proj.name] > 1:
            proj.name = proj.root.name = f"{proj.name} ({names[proj.name]})"
    rels: Dict[Path, str] = {}
    used: set = set()
    for proj in projects:
        if excludes:
            _apply_excludes(proj, excludes)
        proj.root.prune()
        proj.root.sort()
        for node, shown in _tree_files(proj.root):
            if node.path not in rels:
                # 개발도구의 프로젝트는 그 도구에서 보이는 경로를 쓴다: Eclipse 계열은 프로젝트 안의 이름
                # (FreeRTOS/tasks.c), Visual Studio 는 솔루션 탐색기의 필터 경로(소스 파일/유틸/util.c).
                real = _relative(node.path, proj.base)
                rel = shown if proj.view_paths else real
                if len(projects) > 1:
                    rel = f"{proj.name}/{rel}"
                if rel in used:             # 같은 필터에 이름이 같은 파일이 둘이면 실제 경로를 덧붙인다
                    rel = f"{rel} [{real}]"
                while rel in used:
                    rel += "'"
                used.add(rel)
                rels[node.path] = rel
            node.rel = rels[node.path]
    return Workspace(projects)


def _tree_files(node: Node, parts: Tuple[str, ...] = ()) -> Iterator[Tuple[Node, str]]:
    """(파일 노드, 트리에서의 경로)."""
    for c in node.children:
        if c.kind == "file":
            yield c, "/".join(parts + (c.name,))
        else:
            yield from _tree_files(c, parts + (c.name,))


def _apply_excludes(proj: Project, excludes: List[str]) -> None:
    def keep(node: Node) -> bool:
        rel = _relative(node.path, proj.base)
        return not any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(node.name, pat) for pat in excludes)

    def visit(node: Node) -> None:
        node.children = [c for c in node.children if c.kind != "file" or keep(c)]
        for c in node.children:
            visit(c)

    visit(proj.root)
