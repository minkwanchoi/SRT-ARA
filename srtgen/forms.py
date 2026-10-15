"""수집한 예외사유를 매뉴얼 부록 7 양식의 보고서 구조로 만든다.

여기서 만든 구조(Report)를 md, hwpx 출력기가 각자 형식으로 옮긴다.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from . import criteria
from .notation import TEST_TYPES
from .scanner import Block, ExceptionItem, Occurrence, ScanResult


@dataclass
class Para:
    text: str
    style: str = ""      # "" (칸 기본) | "center" | "caption" | "code"


@dataclass
class CodeBox:
    caption: str
    lines: List[Tuple[int, str]]
    images: List[Path] = field(default_factory=list)   # 있으면 글자 대신 그림으로 넣는다


@dataclass
class Picture:
    path: Path
    caption: str = ""


Content = Union[Para, CodeBox, Picture]


@dataclass
class Cell:
    content: List[Content]
    span: int = 1
    kind: str = "value"   # "label" | "value" | "center" | "left"(함수명처럼 양쪽 정렬하면 벌어지는 글) | "block"


@dataclass
class FormTable:
    widths: List[float]           # 열 너비(mm)
    rows: List[List[Cell]]


@dataclass
class Section:
    heading: str
    table: FormTable


@dataclass
class Report:
    test: str
    filename: str
    title: List[str]
    sections: List[Section]
    notes: List[str] = field(default_factory=list)


@dataclass
class Options:
    project: str = "OOO체계개발사업"     # 사업명
    csc: str = "OOOO CSC"                # CSC명
    code_mode: str = "text"       # "text" | "image"
    out_dir: Path = Path("out")
    image_lines: int = 30         # 그림 한 장에 넣을 최대 줄 수 (쪽 넘김 단위)
    csci: str = "OOOO분석장치"           # CSCI명
    # @첨부 를 찾아도 되는 폴더(연 프로젝트의 폴더). 소스 파일이 있는 폴더 아래는 늘 된다 (project_roots)
    roots: Tuple[Path, ...] = ()

    @property
    def heading(self) -> str:
        """보고서 제목의 앞부분: 사업명 CSCI명 CSC명 (양식 예시 "OOO체계개발사업 OOOO분석장치 운용 CSC")."""
        return report_heading(self.project, self.csci, self.csc)


# 보고서에 넣을 수 있는 첨부(그림). 화면이 다이어그램과 함께 저장하는 .mmd 원본은 보고서에 넣지 않는다.
PICTURE_TYPES = (".png", ".jpg", ".jpeg", ".gif", ".bmp")


def inside(path: Path, roots) -> bool:
    """path 가 roots 의 한 폴더 아래(또는 그 폴더 자체)에 있는가. 심볼릭 링크·`..` 는 풀어서 본다."""
    try:
        target = Path(path).resolve()
    except OSError:
        return False
    for root in roots:
        try:
            r = Path(root).resolve()
        except OSError:
            continue
        if target == r or r in target.parents:
            return True
    return False


def project_roots(projects) -> Tuple[Path, ...]:
    """연 프로젝트(project.Project 목록)의 폴더: 기준 폴더와 프로젝트 파일이 있는 폴더(폴더로 열었으면 그 폴더)."""
    roots = []
    for p in projects:
        roots.append(Path(p.base))
        origin = Path(p.origin)
        roots.append(origin if origin.is_dir() else origin.parent)
    return tuple(dict.fromkeys(roots))


def report_heading(project: str, csci: str, csc: str) -> str:
    return " ".join(p.strip() for p in (project, csci, csc) if p and p.strip())


def label(text: str, span: int = 1) -> Cell:
    return Cell([Para(t) for t in text.split("\n")], span, "label")


def value(text: str, span: int = 1, kind: str = "value") -> Cell:
    return Cell([Para(t) for t in (text.split("\n") if text else [""])], span, kind)


def location(block: Block) -> str:
    """코드위치: 라인이 바뀌어도 찾을 수 있도록 주석 식별자를 함께 적는다."""
    return f"{block.lines}\n또는\n/* {block.tag} */"


# 양식의 열 너비(mm). 행마다 칸 경계가 달라 잘게 나눈 뒤 병합해서 쓴다.
_LOCATION_GRID = [16, 12, 16, 12, 18, 20, 24, 12, 40]   # FA 사유서, 동적시험 보고서
_METRIC_GRID = [16, 12, 16, 28, 16, 18, 44, 20]         # 소스코드메트릭 보고서


class Builder:
    def __init__(self, options: Options):
        self.options = options
        self._image_dir = Path(options.out_dir) / "images"
        self._attached: Dict[str, Path] = {}

    # ---- 코드내용 ----
    def code_box(self, block: Block, ref: bool = False) -> CodeBox:
        parts = [("참조 " if ref else "") + block.tag, block.file]
        if block.function:
            parts.append(block.function)
        parts.append(f"Line {block.lines}")
        box = CodeBox(" | ".join(parts), block.code)
        if self.options.code_mode == "image":
            from . import codeimg
            safe = block.file.replace("/", "_").replace(".", "_")
            stem = f"{block.tag}_{safe}_L{block.start_line}"
            box.images = codeimg.render(block.code, block.language, self._image_dir, stem,
                                        self.options.image_lines)
        return box

    def attachments(self, occ: Occurrence) -> List[Content]:
        out: List[Content] = []
        spec = occ.fields.get("첨부", "")
        for entry in filter(None, (e.strip() for e in spec.replace("\n", ";").split(";"))):
            name, _, caption = entry.partition("|")
            src, why = self._find_attachment(name.strip(), occ.main)
            if src is None:
                out.append(Para(f"[{why}: {name.strip()}]"))
                continue
            out.append(Picture(self._copy_attachment(src), caption.strip()))
        return out

    def _find_attachment(self, name: str, block: Block) -> Tuple[Optional[Path], str]:
        """@첨부 의 그림 파일과, 못 쓰면 그 까닭. 보고서 출력 폴더로 복사되므로 받는 것을 좁힌다(49단계 보안 점검):
        그림 파일(PICTURE_TYPES)만, 절대 경로는 받지 않고, 소스 파일이 있는 폴더나 연 프로젝트 폴더 아래만.
        (그렇지 않으면 남이 만든 저장소의 주석 하나로 PC 의 다른 파일이 보고서에 복사된다)"""
        rel = Path(name)
        if rel.drive or rel.root:
            return None, "첨부하지 않음(절대 경로는 받지 않음)"
        if rel.suffix.lower() not in PICTURE_TYPES:
            return None, "첨부하지 않음(그림 파일만: " + ", ".join(PICTURE_TYPES) + ")"
        base = Path(block.base_dir) if block.base_dir else Path.cwd()
        for folder in (base, Path.cwd()):
            p = folder / rel
            if p.is_file():
                if inside(p, (base,) + tuple(self.options.roots)):
                    return p, ""
                return None, "첨부하지 않음(소스·프로젝트 폴더 밖)"
        return None, "첨부 파일을 찾을 수 없음"

    def _copy_attachment(self, src: Path) -> Path:
        key = str(src.resolve())
        if key not in self._attached:
            self._image_dir.mkdir(parents=True, exist_ok=True)
            dst = self._image_dir / f"attach{len(self._attached) + 1}_{src.name}"
            shutil.copyfile(src, dst)
            self._attached[key] = dst
        return self._attached[key]

    def code_cell(self, item: ExceptionItem, span: int) -> Cell:
        rep = item.representative
        content: List[Content] = [self.code_box(rep.main)]
        content += [self.code_box(r, ref=True) for r in rep.refs]
        fields = item.fields
        for text in fields.get("설명", "").split("\n"):
            if text:
                content.append(Para(text))
        if fields.get("Ref"):
            content.append(Para("Ref. : " + fields["Ref"].replace("\n", " / ")))
        content += self.attachments(rep)
        return Cell(content, span, "block")

    # ---- 양식 ----
    def fa_form(self, item: ExceptionItem) -> FormTable:
        """코딩규칙/취약점 FA 사유서 (부록 7-24)."""
        f = item.fields
        rep = item.representative.main
        if item.test == "S-C":          # 코딩규칙 칸에는 적용한 기준(MISRA-C:2012 등)과 규칙을 함께 적는다
            subject = "코딩\n규칙"
            standard = criteria.coding_standard(f.get("기준", "")) or f.get("기준", "")
            what = "\n".join(filter(None, [standard, f.get("규칙", "")]))
        else:
            subject = "취약점"
            what = f.get("취약점", "")
        # FA내용(규칙명·취약점명)을 쓰지 않았으면 번호로 시험 기준의 목록에서 찾아 쓴다
        content = f.get("FA내용", "") or criteria.derived_content(item.test, f)
        rows = [
            [label(subject), value(what, 3, "center"), label("FA내용"), value(content, 4)],
            [label("개수"), value(str(item.count), 1, "center"), label("파일명"), value(rep.file, 3, "center"),
             label("코드위치\n(라인 또는\n주석정보)"), value(location(rep), 2)],
            [self.code_cell(item, 9)],
            [label("FA분석"), value(f.get("FA분석", ""), 8)],
            [label("결론"), value(f.get("결론", ""), 8)],
            [label("동일사항 파일명 및 코드위치", 9)],
        ]
        return FormTable(_LOCATION_GRID, rows + self.same_locations(item))

    @staticmethod
    def same_locations(item: ExceptionItem) -> List[List[Cell]]:
        """동일사항 표 (번호, 파일명, 코드위치, 비고)."""
        rows = [[label("번호"), label("파일명", 4), label("코드위치", 3), label("비고")]]
        for n, occ in enumerate(item.same, 1):
            b = occ.main
            rows.append([value(str(n), 1, "center"), value(b.file, 4, "center"),
                         value(f"{b.lines} (/* {b.tag} */)", 3, "center"), value(occ.fields.get("비고", ""))])
        if not item.same:
            rows.append([value("-", 1, "center"), value("", 4), value("", 3), value("")])
        return rows

    def metric_form(self, item: ExceptionItem) -> FormTable:
        """소스코드메트릭 제한값 미달성 분석 보고서 (부록 7-25)."""
        f = item.fields
        rep = item.representative.main
        limit = f.get("제한값", "")
        measured = f.get("측정값", "")
        rows = [
            [label("메트릭"), value(f.get("메트릭", ""), 4, "center"), label("제한값\n(측정값)"),
             value(f"{limit}({measured})" if measured else limit, 2, "center")],
            [label("개수"), value(str(item.count), 1, "center"), label("파일명"), value(rep.file, 2, "center"),
             label("함수명"), value(rep.function, 2, "left")],
            [self.code_cell(item, 8)],
            [label("미달성\n사유"), value(f.get("미달성사유", ""), 7)],
            [label("미달성 동일사항 파일명 및 함수명", 8)],
            [label("번호"), label("파일명", 3), label("함수명", 3), label("측정값")],
        ]
        for n, occ in enumerate(item.same, 1):
            b = occ.main
            rows.append([value(str(n), 1, "center"), value(b.file, 3, "center"),
                         value(b.function, 3, "left"), value(occ.fields.get("측정값", ""), 1, "center")])
        if not item.same:
            rows.append([value("-", 1, "center"), value("", 3), value("", 3), value("")])
        return FormTable(_METRIC_GRID, rows)

    def dynamic_form(self, item: ExceptionItem) -> FormTable:
        """SW신뢰성 동적시험 미달성 분석 보고서 (부록 7-26)."""
        f = item.fields
        rep = item.representative.main
        reason = Cell([Para(t) for t in f.get("미달성사유", "").split("\n")], 8)
        if f.get("커버리지"):
            level = criteria.coverage(f["커버리지"]) or f["커버리지"]
            reason.content.insert(0, Para(f"코드 실행률 기준: {level}"))
        if f.get("요구사항"):
            reason.content.append(Para(f"[{f['요구사항']}]", "center"))
        rows = [
            [label("개수"), value(str(item.count), 1, "center"), label("파일명"), value(rep.file, 3, "center"),
             label("코드위치\n(라인 또는\n주석정보)"), value(location(rep), 2)],
            [self.code_cell(item, 9)],
            [label("미달성\n사유"), reason],
            [label("미달성 동일사항 파일명 및 코드위치", 9)],
        ]
        return FormTable(_LOCATION_GRID, rows + self.same_locations(item))

    def report(self, test: str, items: List[ExceptionItem]) -> Report:
        ttype = TEST_TYPES[test]
        form = {"S-C": self.fa_form, "S-W": self.fa_form, "S-M": self.metric_form, "D": self.dynamic_form}[test]
        sections = []
        for n, item in enumerate(items, 1):
            heading = f"{n}. SW신뢰성시험-{ttype.name}-ID{item.ex_id} ({item.tag})"
            sections.append(Section(heading, form(item)))
        notes = []
        if test != "S-M":
            notes.append("※ 코드위치의 라인은 보고서 생성 시점 기준이며, 소스코드가 변경되어도 "
                         "주석 식별자(/* SRT-... */)로 해당 위치를 찾을 수 있음")
        title = [self.options.heading, ttype.report]
        return Report(test, ttype.filename, title, sections, notes)


def build_reports(result: ScanResult, options: Options) -> List[Report]:
    builder = Builder(options)
    reports = []
    for test in TEST_TYPES:
        items = result.by_test(test)
        if items:
            reports.append(builder.report(test, items))
    return reports
