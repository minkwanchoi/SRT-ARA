"""보고서를 HWPX(OWPML, KS X 6101) 로 출력한다.

한글 프로그램 없이 ZIP + XML 을 직접 만든다. 문서 뼈대(header.xml 등)는
templates/hwpx 의 빈 문서를 쓰고, 필요한 글꼴/테두리/글자/문단 모양만 추가한다.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import re
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.sax.saxutils import escape

from . import NAME, imageinfo
from .forms import Cell, CodeBox, FormTable, Para, Picture, Report

TEMPLATE_DIR = Path(__file__).parent / "templates" / "hwpx"

MM = 7200 / 25.4                      # 1mm 의 HWPUNIT
PAGE_W, PAGE_H = 59528, 84186         # A4
MARGIN_LR = round(20 * MM)
TEXT_W = PAGE_W - 2 * MARGIN_LR
TABLE_OUT = 283                       # 표 바깥 여백
TABLE_W = TEXT_W - 2 * TABLE_OUT
CELL_LR, CELL_TB = 510, 141           # 칸 안 여백
BLOCK_PAD = 700                       # 코드내용 칸 안 여백
PX = 75                               # 96dpi 기준 1픽셀의 HWPUNIT

# header.xml 에 추가하는 모양의 ID (빈 문서: 글꼴 0~1, 테두리 1~2, 글자 0~6, 문단 0~19)
FONT_DOTUM, FONT_BATANG, FONT_MONO = 0, 1, 2
BF_CELL, BF_LABEL, BF_BOX = 3, 4, 5
CH_BODY, CH_TITLE, CH_LABEL, CH_CODE, CH_CAPTION, CH_HEADING, CH_NOTE = 0, 7, 8, 9, 10, 11, 12
PA_BODY, PA_CENTER, PA_CELL, PA_CODE, PA_TITLE, PA_LEFT, PA_HEADING, PA_CELL_LEFT = 0, 20, 21, 22, 23, 24, 25, 26

_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def _text(s: str) -> str:
    return escape(_ILLEGAL.sub("", s.replace("\t", "    ").replace("\n", " ")))


# ---------------------------------------------------------------- header.xml
def _font(fid: int, face: str) -> str:
    return (f'<hh:font id="{fid}" face="{face}" type="TTF" isEmbedded="0"><hh:typeInfo '
            'familyType="FCAT_GOTHIC" weight="6" proportion="0" contrast="0" strokeVariation="1" '
            'armStyle="1" letterform="1" midline="1" xHeight="1"/></hh:font>')


def _border_fill(bid: int, fill: Optional[str] = None) -> str:
    sides = "".join(f'<hh:{s}Border type="SOLID" width="0.12 mm" color="#000000"/>'
                    for s in ("left", "right", "top", "bottom"))
    brush = (f'<hc:fillBrush><hc:winBrush faceColor="{fill}" hatchColor="#000000" alpha="0"/></hc:fillBrush>'
             if fill else "")
    return (f'<hh:borderFill id="{bid}" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">'
            '<hh:slash type="NONE" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" Crooked="0" isCounter="0"/>'
            f'{sides}<hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>{brush}</hh:borderFill>')


def _char_pr(cid: int, height: int, font: int, bold: bool = False, underline: bool = False) -> str:
    def langs(v: object) -> str:
        return " ".join(f'{k}="{v}"' for k in ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user"))
    return (f'<hh:charPr id="{cid}" height="{height}" textColor="#000000" shadeColor="none" useFontSpace="0" '
            'useKerning="0" symMark="NONE" borderFillIDRef="2">'
            f'<hh:fontRef {langs(font)}/><hh:ratio {langs(100)}/><hh:spacing {langs(0)}/>'
            f'<hh:relSz {langs(100)}/><hh:offset {langs(0)}/>'
            + ("<hh:bold/>" if bold else "")
            + f'<hh:underline type="{"BOTTOM" if underline else "NONE"}" shape="SOLID" color="#000000"/>'
            '<hh:strikeout shape="NONE" color="#000000"/><hh:outline type="NONE"/>'
            '<hh:shadow type="NONE" color="#C0C0C0" offsetX="10" offsetY="10"/></hh:charPr>')


def _para_pr(pid: int, align: str, spacing: int, left: int = 0, right: int = 0, prev: int = 0,
             nxt: int = 0, border: int = 2, connect: int = 0, offset: int = 0) -> str:
    def body(k: int) -> str:   # 구버전 호환 분기는 여백 단위가 2배이다
        return ('<hh:margin><hc:intent value="0" unit="HWPUNIT"/>'
                f'<hc:left value="{left * k}" unit="HWPUNIT"/><hc:right value="{right * k}" unit="HWPUNIT"/>'
                f'<hc:prev value="{prev * k}" unit="HWPUNIT"/><hc:next value="{nxt * k}" unit="HWPUNIT"/></hh:margin>'
                f'<hh:lineSpacing type="PERCENT" value="{spacing}" unit="HWPUNIT"/>')
    return (f'<hh:paraPr id="{pid}" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="1" '
            'suppressLineNumbers="0" checked="0" textDir="LTR">'
            f'<hh:align horizontal="{align}" vertical="BASELINE"/><hh:heading type="NONE" idRef="0" level="0"/>'
            '<hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="BREAK_WORD" widowOrphan="0" '
            'keepWithNext="0" keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/>'
            '<hh:autoSpacing eAsianEng="0" eAsianNum="0"/>'
            '<hp:switch><hp:case hp:required-namespace="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar">'
            f'{body(1)}</hp:case><hp:default>{body(2)}</hp:default></hp:switch>'
            f'<hh:border borderFillIDRef="{border}" offsetLeft="{offset}" offsetRight="{offset}" '
            f'offsetTop="{offset}" offsetBottom="{offset}" connect="{connect}" ignoreMargin="0"/></hh:paraPr>')


def _append(header: str, container: str, items: List[str]) -> str:
    m = re.search(rf'<hh:{container} itemCnt="(\d+)">', header)
    assert m, container
    header = header[:m.start()] + f'<hh:{container} itemCnt="{int(m.group(1)) + len(items)}">' + header[m.end():]
    close = header.index(f"</hh:{container}>")
    return header[:close] + "".join(items) + header[close:]


def build_header() -> str:
    header = (TEMPLATE_DIR / "header.xml").read_text(encoding="utf-8")
    header = re.sub(
        r'(<hh:fontface lang="\w+" fontCnt=")(\d+)(">.*?)(</hh:fontface>)',
        lambda m: m.group(1) + str(int(m.group(2)) + 1) + m.group(3) + _font(FONT_MONO, "굴림체") + m.group(4),
        header, flags=re.S)
    header = _append(header, "borderFills", [
        _border_fill(BF_CELL), _border_fill(BF_LABEL, "#E5E5E5"), _border_fill(BF_BOX)])
    header = _append(header, "charProperties", [
        _char_pr(CH_TITLE, 1500, FONT_DOTUM, bold=True, underline=True),
        _char_pr(CH_LABEL, 1000, FONT_DOTUM),
        _char_pr(CH_CODE, 900, FONT_MONO),
        _char_pr(CH_CAPTION, 900, FONT_DOTUM, bold=True),
        _char_pr(CH_HEADING, 1100, FONT_DOTUM, bold=True),
        _char_pr(CH_NOTE, 900, FONT_BATANG),
    ])
    header = _append(header, "paraProperties", [
        _para_pr(PA_CENTER, "CENTER", 130),
        _para_pr(PA_CELL, "JUSTIFY", 130),
        _para_pr(PA_CODE, "LEFT", 120, left=300, right=300, border=BF_BOX, connect=1, offset=200),
        _para_pr(PA_TITLE, "CENTER", 150),
        _para_pr(PA_LEFT, "LEFT", 130, nxt=200),
        _para_pr(PA_HEADING, "LEFT", 160, prev=600, nxt=200),
        _para_pr(PA_CELL_LEFT, "LEFT", 130),
    ])
    return header


# -------------------------------------------------------------- section0.xml
class _Writer:
    def __init__(self, compact: bool):
        self.compact = compact
        self.images: Dict[str, Tuple[str, Path]] = {}   # 경로 -> (ID, 파일)
        self._next_id = 1000000000
        self.preview: List[str] = []

    def new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    # ---- 문단 ----
    def para(self, text: str, para_pr: int, char_pr: int, page_break: bool = False, lead: str = "") -> str:
        run = (f'<hp:run charPrIDRef="{char_pr}"><hp:t>{_text(text)}</hp:t></hp:run>' if text
               else f'<hp:run charPrIDRef="{char_pr}"/>')
        return (f'<hp:p id="0" paraPrIDRef="{para_pr}" styleIDRef="0" pageBreak="{int(page_break)}" '
                f'columnBreak="0" merged="0">{lead}{run}</hp:p>')

    def object_para(self, obj: str, para_pr: int) -> str:
        return (f'<hp:p id="0" paraPrIDRef="{para_pr}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
                f'<hp:run charPrIDRef="0">{obj}<hp:t/></hp:run></hp:p>')

    # ---- 그림 ----
    def picture(self, path: Path, max_w: int, scale: float, caption: str) -> Optional[str]:
        dims = imageinfo.size(path)
        if dims is None or imageinfo.media_type(path) is None:
            return None
        key = str(path.resolve())
        if key not in self.images:
            self.images[key] = (f"image{len(self.images) + 1}", path)
        item_id = self.images[key][0]
        w, h = dims[0] * PX * scale, dims[1] * PX * scale
        if w > max_w:
            w, h = max_w, h * max_w / w
        w, h = round(w), round(h)
        pid = self.new_id()
        comment = _text(f"그림입니다.\n원본 그림의 이름: {path.name}\n"
                        f"원본 그림의 크기: 가로 {dims[0]}pixel, 세로 {dims[1]}pixel\n{caption}".rstrip())
        return (
            f'<hp:pic id="{pid}" zOrder="0" numberingType="PICTURE" textWrap="TOP_AND_BOTTOM" '
            f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0" instid="{pid}" reverse="0">'
            f'<hp:offset x="0" y="0"/><hp:orgSz width="{w}" height="{h}"/><hp:curSz width="0" height="0"/>'
            '<hp:flip horizontal="0" vertical="0"/><hp:rotationInfo angle="0" centerX="0" centerY="0" rotateimage="1"/>'
            '<hp:renderingInfo><hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
            '<hc:scaMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
            '<hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/></hp:renderingInfo>'
            f'<hc:img binaryItemIDRef="{item_id}" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>'
            f'<hp:imgRect><hc:pt0 x="0" y="0"/><hc:pt1 x="{w}" y="0"/><hc:pt2 x="{w}" y="{h}"/>'
            f'<hc:pt3 x="0" y="{h}"/></hp:imgRect>'
            '<hp:imgClip left="0" right="0" top="0" bottom="0"/><hp:inMargin left="0" right="0" top="0" bottom="0"/>'
            '<hp:imgDim dimwidth="0" dimheight="0"/><hp:effects/>'
            f'<hp:sz width="{w}" widthRelTo="ABSOLUTE" height="{h}" heightRelTo="ABSOLUTE" protect="0"/>'
            '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
            'vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
            '<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
            f'<hp:shapeComment>{comment}</hp:shapeComment></hp:pic>')

    # ---- 표 ----
    def cell_paras(self, cell: Cell, inner_w: int) -> str:
        para_pr, char_pr = {
            "label": (PA_CENTER, CH_LABEL), "center": (PA_CENTER, CH_BODY), "left": (PA_CELL_LEFT, CH_BODY),
        }.get(cell.kind, (PA_CELL, CH_BODY))
        out: List[str] = []
        for i, c in enumerate(cell.content):
            if isinstance(c, Para):
                if c.style == "center":
                    out.append(self.para(c.text, PA_CENTER, char_pr))
                else:
                    out.append(self.para(c.text, para_pr, char_pr))
            elif isinstance(c, CodeBox):
                out.append(self.para(c.caption, PA_LEFT, CH_CAPTION))
                pics = [self.picture(p, inner_w, 0.5, c.caption) for p in c.images]
                if pics and all(pics):
                    out += [self.object_para(p, PA_LEFT) for p in pics]
                else:
                    width = max(3, max((len(str(n)) for n, _ in c.lines), default=3))
                    out += [self.para(f"{n:>{width}}: {t}", PA_CODE, CH_CODE) for n, t in c.lines]
                    out.append(self.para("", PA_LEFT, CH_NOTE))
            elif isinstance(c, Picture):
                pic = self.picture(c.path, inner_w, imageinfo.scale(c.path), c.caption)
                if pic is None:
                    out.append(self.para(f"[그림을 넣을 수 없음: {c.path.name}]", para_pr, char_pr))
                    continue
                out.append(self.object_para(pic, PA_CENTER))
                if c.caption:
                    out.append(self.para(c.caption, PA_CENTER, CH_NOTE))
        return "".join(out) or self.para("", para_pr, char_pr)

    def table(self, table: FormTable) -> str:
        total = sum(table.widths)
        widths = [round(w * TABLE_W / total) for w in table.widths]
        widths[-1] += TABLE_W - sum(widths)
        row_h = 1700
        rows: List[str] = []
        for r, row in enumerate(table.rows):
            cells: List[str] = []
            col = 0
            for cell in row:
                w = sum(widths[col:col + cell.span])
                block = cell.kind == "block"
                lr, tb = (BLOCK_PAD, BLOCK_PAD // 2) if block else (CELL_LR, CELL_TB)
                fill = BF_LABEL if cell.kind == "label" else BF_CELL
                cells.append(
                    f'<hp:tc name="" header="0" hasMargin="{int(block)}" protect="0" editable="0" dirty="0" '
                    f'borderFillIDRef="{fill}">'
                    '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
                    'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
                    f'{self.cell_paras(cell, w - 2 * lr - 1000)}</hp:subList>'
                    f'<hp:cellAddr colAddr="{col}" rowAddr="{r}"/><hp:cellSpan colSpan="{cell.span}" rowSpan="1"/>'
                    f'<hp:cellSz width="{w}" height="{row_h}"/>'
                    f'<hp:cellMargin left="{lr}" right="{lr}" top="{tb}" bottom="{tb}"/></hp:tc>')
                col += cell.span
            assert col == len(widths), f"행 {r}: 열 병합 합계 {col} != {len(widths)}"
            rows.append("<hp:tr>" + "".join(cells) + "</hp:tr>")
        tid = self.new_id()
        return (
            f'<hp:tbl id="{tid}" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" '
            f'lock="0" dropcapstyle="None" pageBreak="CELL" repeatHeader="0" rowCnt="{len(table.rows)}" '
            f'colCnt="{len(widths)}" cellSpacing="0" borderFillIDRef="{BF_CELL}" noAdjust="0">'
            f'<hp:sz width="{TABLE_W}" widthRelTo="ABSOLUTE" height="{row_h * len(table.rows)}" '
            'heightRelTo="ABSOLUTE" protect="0"/>'
            '<hp:pos treatAsChar="0" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
            'vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
            f'<hp:outMargin left="{TABLE_OUT}" right="{TABLE_OUT}" top="{TABLE_OUT}" bottom="{TABLE_OUT}"/>'
            f'<hp:inMargin left="{CELL_LR}" right="{CELL_LR}" top="{CELL_TB}" bottom="{CELL_TB}"/>'
            + "".join(rows) + "</hp:tbl>")

    # ---- 구역 ----
    def section(self, report: Report) -> str:
        sec_pr = (TEMPLATE_DIR / "secpr.xml").read_text(encoding="utf-8")
        top, bottom, head = round(20 * MM), round(15 * MM), round(10 * MM)
        sec_pr = re.sub(r"<hp:margin [^>]*/>",
                        f'<hp:margin header="{head}" footer="{head}" gutter="0" left="{MARGIN_LR}" '
                        f'right="{MARGIN_LR}" top="{top}" bottom="{bottom}"/>', sec_pr, count=1)
        lead = f'<hp:run charPrIDRef="0">{sec_pr}</hp:run>'
        out = [(TEMPLATE_DIR / "section_open.xml").read_text(encoding="utf-8")]
        for i, line in enumerate(report.title):
            out.append(self.para(line, PA_TITLE, CH_TITLE, lead=lead if i == 0 else ""))
            self.preview.append(line)
        for n, sec in enumerate(report.sections):
            out.append(self.para(sec.heading, PA_HEADING, CH_HEADING,
                                 page_break=(n > 0 and not self.compact)))
            out.append(self.object_para(self.table(sec.table), PA_BODY))
            out += [self.para(note, PA_BODY, CH_NOTE) for note in report.notes]
            self.preview.append(sec.heading)
        out.append("</hs:sec>")
        return "".join(out)


# ------------------------------------------------------------------- package
def _content_hpf(title: str, images: Dict[str, Tuple[str, Path]], when: datetime.date) -> str:
    ns = re.search(r"<hs:sec ([^>]*)>", (TEMPLATE_DIR / "section_open.xml").read_text(encoding="utf-8")).group(1)
    stamp = when.strftime("%Y-%m-%dT00:00:00Z")
    items = []
    for item_id, path in images.values():
        digest = base64.b64encode(hashlib.md5(path.read_bytes()).digest()).decode()
        items.append(f'<opf:item id="{item_id}" href="BinData/{item_id}{path.suffix.lower()}" '
                     f'media-type="{imageinfo.media_type(path)}" isEmbeded="1" hashkey="{digest}"/>')

    def meta(name: str, text: str = "") -> str:
        return (f'<opf:meta name="{name}" content="text">{text}</opf:meta>' if text
                else f'<opf:meta name="{name}" content="text"/>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
            f'<opf:package {ns} version="" unique-identifier="" id="">'
            f'<opf:metadata><opf:title>{_text(title)}</opf:title><opf:language>ko</opf:language>'
            + meta("creator", NAME) + meta("subject") + meta("description") + meta("lastsaveby", NAME)
            + meta("CreatedDate", stamp) + meta("ModifiedDate", stamp) + meta("date", when.isoformat())
            + meta("keyword") + '</opf:metadata><opf:manifest>'
            '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
            + "".join(items)
            + '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
            '<opf:item id="settings" href="settings.xml" media-type="application/xml"/></opf:manifest>'
            '<opf:spine><opf:itemref idref="header" linear="yes"/><opf:itemref idref="section0" linear="yes"/>'
            '</opf:spine></opf:package>')


def render(report: Report, out_dir: Path, compact: bool = False,
           when: Optional[datetime.date] = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    writer = _Writer(compact)
    section = writer.section(report)
    when = when or datetime.date.today()
    path = out_dir / (report.filename + ".hwpx")

    def add(z: zipfile.ZipFile, name: str, data: bytes, method: int = zipfile.ZIP_DEFLATED) -> None:
        info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))   # 같은 입력이면 같은 파일이 나오도록 시각 고정
        info.compress_type = method
        z.writestr(info, data)

    def template(name: str) -> bytes:
        return (TEMPLATE_DIR / name).read_bytes()

    with zipfile.ZipFile(path, "w") as z:
        add(z, "mimetype", b"application/hwp+zip", zipfile.ZIP_STORED)
        add(z, "version.xml", template("version.xml"), zipfile.ZIP_STORED)
        add(z, "Contents/header.xml", build_header().encode("utf-8"))
        for item_id, src in writer.images.values():
            add(z, f"BinData/{item_id}{src.suffix.lower()}", src.read_bytes(), zipfile.ZIP_STORED)
        add(z, "Contents/section0.xml", section.encode("utf-8"))
        add(z, "Preview/PrvText.txt", ("\r\n".join(writer.preview) + "\r\n").encode("utf-8"))
        add(z, "settings.xml", template("settings.xml"))
        add(z, "META-INF/container.rdf", template("container.rdf"))
        add(z, "Contents/content.hpf", _content_hpf(" ".join(report.title), writer.images, when).encode("utf-8"))
        add(z, "META-INF/container.xml", template("container.xml"))
        add(z, "META-INF/manifest.xml", template("manifest.xml"))
    return path
