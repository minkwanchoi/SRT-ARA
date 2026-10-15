"""보고서를 Markdown 으로 출력한다.

양식에 병합 칸이 있어 표는 HTML 로 쓴다. 표 안에는 빈 줄을 두지 않는다
(Markdown 에서 빈 줄은 HTML 블록을 끝낸다).
"""
from __future__ import annotations

import html
import os
from pathlib import Path
from typing import List

from . import imageinfo
from .forms import Cell, CodeBox, FormTable, Para, Picture, Report


def _esc(text: str) -> str:
    """HTML 글 자리(태그 사이)용. 따옴표는 글 자리에서 해가 없으므로 바꾸지 않는다(md 를 사람이 읽기 좋게).
    속성 자리(alt="…", src="…")에는 반드시 _attr 를 쓴다."""
    return html.escape(text, quote=False)


def _attr(text: str) -> str:
    """HTML 속성 값 자리용: 따옴표까지 바꾼다. 이 HTML 은 화면의 양식 미리보기에도 그대로 들어가므로, 캡션에 든
    따옴표가 속성을 닫고 onload 같은 속성을 만들면 스크립트가 돈다(49단계 보안 점검)."""
    return html.escape(text, quote=True)


def _rel(path: Path, base: Path) -> str:
    """그림의 상대 경로(src 속성 값). 속성 자리이므로 _attr 로 바꿔 돌려준다."""
    return _attr(Path(os.path.relpath(path, base)).as_posix())


def _content(cell: Cell, base: Path) -> str:
    out: List[str] = []
    paras: List[str] = []

    def flush() -> None:
        if paras:
            out.append("<br>".join(paras))
            paras.clear()

    for c in cell.content:
        if isinstance(c, Para):
            text = _esc(c.text)
            if c.style == "center":
                flush()
                out.append(f'<div align="center">{text}</div>')
            else:
                paras.append(text)
        elif isinstance(c, CodeBox):
            flush()
            out.append(f"<b>{_esc(c.caption)}</b>")
            if c.images:
                out += [f'<br><img src="{_rel(p, base)}" alt="{_attr(c.caption)}">' for p in c.images]
                out.append("<br>")
            else:
                width = max((len(str(n)) for n, _ in c.lines), default=3)
                body = "\n".join(f"{n:>{max(width, 3)}}: {_esc(t)}".rstrip() for n, t in c.lines)
                out.append(f"<pre>{body}</pre>")
        elif isinstance(c, Picture):
            flush()
            cap = f"<br><i>{_esc(c.caption)}</i>" if c.caption else ""
            dims, ratio = imageinfo.size(c.path), imageinfo.scale(c.path)
            width = f' width="{round(dims[0] * ratio)}"' if dims and ratio != 1.0 else ""
            out.append(f'<div align="center"><img src="{_rel(c.path, base)}" alt="{_attr(c.caption)}"{width}>'
                       f'{cap}</div>')
    flush()
    return "".join(out)


def _table(table: FormTable, base: Path) -> str:
    total = sum(table.widths)
    lines = ["<table>", "<colgroup>" + "".join(
        f'<col width="{w * 100 / total:.1f}%">' for w in table.widths) + "</colgroup>"]
    for row in table.rows:
        cells = []
        for cell in row:
            tag = "th" if cell.kind == "label" else "td"
            attrs = f' colspan="{cell.span}"' if cell.span > 1 else ""
            if cell.kind in ("label", "center"):
                attrs += ' align="center"'
            cells.append(f"<{tag}{attrs}>{_content(cell, base)}</{tag}>")
        lines.append("<tr>" + "".join(cells) + "</tr>")
    lines.append("</table>")
    return "\n".join(lines)


def render(report: Report, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    parts = ["# " + " ".join(report.title), ""]
    for section in report.sections:
        parts += ["## " + section.heading, "", _table(section.table, out_dir), ""]
    for note in report.notes:
        parts += [note, ""]
    path = out_dir / (report.filename + ".md")
    path.write_bytes("\n".join(parts).encode("utf-8"))        # 줄바꿈 \n 그대로 (Python 3.9 호환)
    return path
