"""수집 결과로 산출물(요약, json, md, hwpx)을 만든다. 명령줄과 웹 UI 가 함께 쓴다."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Sequence

from . import codeimg, render_hwpx, render_md, summary
from .forms import Options, build_reports
from .scanner import ScanResult

FORMATS = ("md", "hwpx")


def write_outputs(result: ScanResult, out: Path, project: str, csc: str,
                  formats: Iterable[str] = FORMATS, code_mode: str = "text",
                  compact: bool = False, projects: Sequence = (), csci: str = "") -> List[Path]:
    """project·csci·csc 는 보고서 제목의 사업명·CSCI명·CSC명이다.
    projects 는 읽은 소스 구성(project.Project 목록)으로, 요약에 적는다."""
    formats = set(formats)
    if code_mode == "image" and not codeimg.available():
        code_mode = "text"
    out.mkdir(parents=True, exist_ok=True)
    options = Options(project=project, csci=csci, csc=csc, code_mode=code_mode, out_dir=out)
    reports = build_reports(result, options)
    written = [summary.write_json(result, out),
               summary.write_summary(result, out, options.heading, projects)]
    for report in reports:
        if "md" in formats:
            written.append(render_md.render(report, out))
        if "hwpx" in formats:
            written.append(render_hwpx.render(report, out, compact))
    return written
