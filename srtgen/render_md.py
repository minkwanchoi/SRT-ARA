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
    return html.escape(text, quote=False)


def _rel(path: Path, base: Path) -> str:
    return Path(os.path.relpath(path, base)).as_posix()


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
                out += [f'<br><img src="{_rel(p, base)}" alt="{_esc(c.caption)}">' for p in c.images]
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
            out.append(f'<div align="center"><img src="{_rel(c.path, base)}" alt="{_esc(c.caption)}"{width}>'
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
