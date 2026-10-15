"""설정 ▸ 정보: 소프트웨어 정보와 오픈소스 정보.

오픈소스 정보의 원본은 THIRD_PARTY.md 다(화면이 따로 목록을 갖지 않는다). 표의 줄과 "라이선스 전문" 목록을 읽고,
"공개본 제외" 표시 사이에 있는 것은 내부용(공개본에는 없음)으로 표시한다. 고지 전문은 정해진 파일만 읽어 보인다.
"""
from __future__ import annotations

import importlib.metadata
import platform
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

from . import NAME, NAME_FULL, NAME_KO, VERSION_LABEL, codeimg, criteria

ROOT = Path(__file__).resolve().parent.parent            # 도구 폴더 (THIRD_PARTY.md, LICENSE, licenses/)
PAPER = ("「무기체계 소프트웨어 신뢰성 시험에서 예외사유의 효율적 관리 방안」, "
         "한국군사과학기술학회 2018년 종합학술대회")
START, END = "<!-- 공개본 제외 시작 -->", "<!-- 공개본 제외 끝 -->"
_DOC_LINE = re.compile(r"^- `((?:licenses/)?[^`/]+)` — (.+)$")


def bundled_python(root: Path = ROOT) -> bool:
    """폐쇄망용 묶음에 든 휴대용 Python(도구 폴더의 python/)으로 돌고 있는가."""
    return Path(sys.prefix).resolve() == (root / "python").resolve()


def _version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return ""


def _license(package: str, fallback: str) -> str:
    """설치된 패키지가 스스로 밝힌 라이선스. 설치되어 있지 않으면 fallback(일반적으로 알려진 값)."""
    try:
        meta = importlib.metadata.metadata(package)
    except importlib.metadata.PackageNotFoundError:
        return fallback
    value = meta.get("License-Expression") or ""
    if not value:
        value = next((c.split("::")[-1].strip() for c in meta.get_all("Classifier") or []
                      if c.startswith("License ::")), "") or (meta.get("License") or "").split("\n")[0]
    return value.strip() or fallback


def copyright_line(root: Path = ROOT) -> str:
    """공개본의 LICENSE 에 적힌 저작권 줄. 내부용(배포 전)에는 LICENSE 가 없다."""
    try:
        text = (root / "LICENSE").read_text(encoding="utf-8")
    except OSError:
        return ""
    return next((line.strip() for line in text.splitlines() if line.strip().startswith("Copyright")), "")


def software(paths: Dict[str, str], mermaid: bool, root: Path = ROOT) -> List[List[str]]:
    """소프트웨어 정보: [항목, 내용] 목록."""
    holder = copyright_line(root)
    pillow, pygments = _version("Pillow"), _version("Pygments")
    rows = [
        ["이름", f"{NAME}({NAME_KO})"],
        ["영문 이름", NAME_FULL],
        ["버전", f"{VERSION_LABEL} (명령 이름 srtgen)"],
        ["따르는 기준", criteria.MANUAL],
        ["바탕 논문", PAPER],
        ["저작권·라이선스", (f"{holder}. 도구 코드는 MIT 라이선스(LICENSE)" if holder else
                       "배포 전(내부용). 공개본의 도구 코드는 MIT 라이선스이며 저작권자는 공개할 때 정한다")
         + ". 함께 넣은 외부 소프트웨어·자료는 각자의 조건을 따른다(오픈소스 정보 탭)"],
        ["Python", f"{platform.python_version()} ({sys.executable})"],
        ["운영체제", platform.platform()],
        ["코드 그림(Pillow)", f"있음 {pillow}".strip() if codeimg.available() else "없음 (--code image 는 글자 발췌로 대신함)"],
        ["구문 강조(Pygments)", f"있음 {pygments}" if pygments else "없음"],
        ["다이어그램(Mermaid)", "있음" if mermaid else "없음 (다이어그램 추가만 쓸 수 없음)"],
    ]
    rows += [[name, path] for name, path in paths.items()]
    rows.append(["도구 폴더", str(root)])
    return rows


def _cells(line: str) -> List[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def third_party(root: Path = ROOT) -> dict:
    """THIRD_PARTY.md 의 함께 넣은 것(표)과 고지 파일(라이선스 전문 목록)."""
    try:
        lines = (root / "THIRD_PARTY.md").read_text(encoding="utf-8").splitlines()
    except OSError:
        return {"components": [], "documents": [], "error": "THIRD_PARTY.md 를 읽을 수 없습니다."}
    components, documents = [], []
    internal = False
    for line in lines:
        mark = line.strip()
        if mark in (START, END):
            internal = mark == START
            continue
        if line.startswith("| ") and not line.startswith(("| 이름 ", "| ---")):
            cells = _cells(line)
            if len(cells) == 7:
                name, version, file, size, purpose, license_, source = cells
                rel = file.strip("`")
                components.append({"name": name, "version": version, "file": rel, "size": size,
                                   "purpose": purpose, "license": license_.replace("`", ""), "source": source,
                                   "internal": internal, "present": (root / rel).is_file()})
            continue
        m = _DOC_LINE.match(line)
        if m:
            documents.append({"name": m.group(1), "about": m.group(2).replace("`", ""), "internal": internal,
                              "present": (root / m.group(1)).is_file()})
    pillow, pygments = _version("Pillow"), _version("Pygments")
    not_bundled = [
        {"name": "Python", "version": platform.python_version(), "license": "PSF License",
         "purpose": ("실행 환경. 폐쇄망용 묶음에 든 휴대용 판(python/, 고지는 python/LICENSE.txt)"
                     if bundled_python(root) else "실행 환경. 사용자 PC에 설치된 것을 쓴다"), "installed": True},
        {"name": "Pillow", "version": pillow, "license": _license("Pillow", "MIT-CMU (HPND)"),
         "purpose": "--code image(코드를 그림으로). 없으면 글자 발췌", "installed": codeimg.available()},
        {"name": "Pygments", "version": pygments, "license": _license("Pygments", "BSD-2-Clause"),
         "purpose": "코드 그림의 구문 강조. 없으면 강조 없이", "installed": bool(pygments)},
    ]
    return {"components": components, "documents": documents, "not_bundled": not_bundled}


def document(name: str, root: Path = ROOT) -> Optional[str]:
    """정해진 문서만 읽는다: LICENSE, CHANGELOG.md, THIRD_PARTY.md, licenses/ 바로 아래 파일."""
    allowed = {"LICENSE", "CHANGELOG.md", "THIRD_PARTY.md"}
    folder = root / "licenses"
    if folder.is_dir():
        allowed |= {f"licenses/{p.name}" for p in folder.iterdir() if p.is_file()}
    if name not in allowed:
        return None
    try:
        return (root / name).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
