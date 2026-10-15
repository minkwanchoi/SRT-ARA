"""수집 결과 요약(md)과 추적용 데이터(json)를 출력한다."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Sequence

from . import NAME, NAME_KO, criteria
from .notation import TEST_TYPES
from .scanner import Block, ScanResult

_SUBJECT = {"S-C": "규칙", "S-W": "취약점", "S-M": "메트릭", "D": "미달성사유"}


def _block(b: Block) -> dict:
    return {"tag": b.tag, "file": b.file, "language": b.language, "function": b.function,
            "start_line": b.start_line, "end_line": b.end_line,
            "code": [{"line": n, "text": t} for n, t in b.code]}


def write_json(result: ScanResult, out_dir: Path) -> Path:
    data = {
        "기준": criteria.basis(),           # 매뉴얼 판과 도구 버전 (개정 뒤에도 어느 기준으로 만든 것인지 알 수 있게)
        "files_scanned": result.files_scanned,
        "exceptions": [{
            "tag": item.tag, "test": item.test, "test_name": TEST_TYPES[item.test].name,
            "id": item.ex_id, "count": item.count, "fields": item.fields,
            "occurrences": [{
                **_block(occ.main), "fields": occ.fields, "references": [_block(r) for r in occ.refs],
            } for occ in item.occurrences],
        } for item in result.items],
        "diagnostics": [{"level": d.level, "file": d.file, "line": d.line, "message": d.message}
                        for d in result.diagnostics],
    }
    path = out_dir / "exceptions.json"
    path.write_bytes(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))   # \n 그대로 (3.9 호환)
    return path


def _criterion(item) -> str:
    """예외사유가 어느 시험 기준에 해당하는지."""
    f = item.fields
    if item.test == "S-C":
        return criteria.coding_standard(f.get("기준", "")) or f.get("기준") or "(기준을 적지 않음)"
    if item.test == "S-W":
        cwe = criteria.cwe_id(f.get("취약점", "") + " " + f.get("Ref", ""))
        if cwe is None:
            return "(CWE 번호를 적지 않음)"
        return ", ".join(criteria.cwe_lists(cwe)) or "(시험 기준의 목록 밖의 CWE)"
    if item.test == "S-M":
        return f.get("메트릭") or "(메트릭을 적지 않음)"
    return criteria.coverage(f.get("커버리지", "")) or f.get("커버리지") or "(실행률 기준을 적지 않음)"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _where(origin, out_dir: Path) -> str:
    """읽은 곳을 출력 폴더 기준 상대 경로로 (예: ../src). 보고서에 이 PC의 절대 경로가 남지 않게 하고,
    다른 PC에서 다시 만들어도 같은 글이 나오게 한다. 드라이브가 달라 상대 경로가 안 되면 절대 경로."""
    try:
        return Path(os.path.relpath(Path(origin).resolve(), Path(out_dir).resolve())).as_posix()
    except ValueError:
        return str(origin)


def write_summary(result: ScanResult, out_dir: Path, title: str, projects: Sequence = ()) -> Path:
    lines: List[str] = [f"# {title} 예외사유 요약", "",
                        f"- 검사한 소스 파일: {result.files_scanned}개 (예외사유 주석 포함 {result.files_with_tags}개)",
                        ""]
    if projects:
        lines += ["## 소스 구성", "", "| 이름 | 종류 | 읽은 곳 | 소스 파일 | 예외사유 주석 포함 |", "|---|---|---|---:|---:|"]
        for proj in projects:
            rels = {n.rel for n in proj.root.files()}
            lines.append(f"| {_cell(proj.name)} | {proj.label} | `{_where(proj.origin, out_dir)}` | {len(rels)} | "
                         f"{len(rels & set(result.paths))} |")
            lines += [f"|  | ⚠ {_cell(w)} |  |  |  |" for w in proj.warnings]
        lines.append("")
    lines += ["## 시험 기준", "", f"기준: {criteria.MANUAL}", "",
              f"이 기준을 따르는 도구 버전: {NAME}({NAME_KO}) ver.{criteria.basis()['도구 버전']}", "",
              "| 시험 | 기준 | 예외사유(ID) 수 |", "|---|---|---:|"]
    for code, ttype in TEST_TYPES.items():
        counts: dict = {}
        for item in result.by_test(code):
            counts[_criterion(item)] = counts.get(_criterion(item), 0) + 1
        lines += [f"| {ttype.title} | {_cell(name)} | {n} |" for name, n in counts.items()]
        if not counts:
            lines.append(f"| {ttype.title} | - | 0 |")
    lines.append("")
    lines += ["## 시험 유형별 건수", "", "| 시험 유형 | 주석 모양 | 예외사유(ID) 수 | 발생 위치 수 | 보고서 |",
              "|---|---|---:|---:|---|"]
    for code, ttype in TEST_TYPES.items():
        items = result.by_test(code)
        report = f"[{ttype.report}]({ttype.filename}.md)" if items else "-"
        lines.append(f"| {ttype.name} | `SRT-{code}-ID##` | {len(items)} | "
                     f"{sum(i.count for i in items)} | {report} |")
    lines += ["", "## 예외사유 목록", "", "| 식별자 | 시험 유형 | 항목 | 대표 위치 | 함수 | 개수 |",
              "|---|---|---|---|---|---:|"]
    for item in result.items:
        rep = item.representative.main
        subject = item.fields.get(_SUBJECT[item.test], "")
        if len(subject) > 40:
            subject = subject[:40] + "…"
        lines.append(f"| `{item.tag}` | {TEST_TYPES[item.test].name} | {_cell(subject)} | "
                     f"{rep.file}:{rep.lines} | {_cell(rep.function)} | {item.count} |")
    lines += ["", "## 점검 결과", ""]
    if result.diagnostics:
        lines += [f"- {d}" for d in result.diagnostics]
    else:
        lines.append("- 잘못 쓴 예외사유 주석 없음")
    lines.append("")
    path = out_dir / "00_예외사유_요약.md"
    path.write_bytes("\n".join(lines).encode("utf-8"))        # 줄바꿈 \n 그대로 (Python 3.9 호환)
    return path
