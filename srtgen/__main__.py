"""명령줄 진입점.

    python -m srtgen <대상> -o <출력 폴더>          보고서 생성
    python -m srtgen serve [대상] -o <출력 폴더>    확인·편집용 웹 화면

대상: 폴더, 소스 파일, 또는 개발도구의 프로젝트 파일(.sln, .vcxproj, .csproj, .project/.cproject,
Makefile, CMakeLists.txt, .ewp, .uvprojx, pom.xml, build.gradle). 여러 개를 섞어 줄 수 있다.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

from . import NAME, NAME_KO, VERSION_LABEL, codeimg, criteria, history, settings
from .forms import report_heading
from .generate import FORMATS, write_outputs
from .project import ProjectError, open_paths, resolve_inputs
from .scanner import scan_entries


def _common(p: argparse.ArgumentParser, nargs: str = "+") -> None:
    p.add_argument("sources", nargs=nargs, type=Path, metavar="대상",
                   help="폴더, 소스 파일, 또는 프로젝트 파일(.sln, .vcxproj, .cproject, Makefile, CMakeLists.txt 등)")
    p.add_argument("-o", "--out", type=Path,
                   help="출력 폴더 (기본: 프로젝트 폴더의 srt_report, srtgen.json 의 \"출력 폴더\"로 바꿈)")
    p.add_argument("--project", help="사업명 (보고서 제목. 기본: 프로젝트 폴더의 srtgen.json)")
    p.add_argument("--csci", help="CSCI명 (보고서 제목). 빈 글이면 제목에서 뺌")
    p.add_argument("--csc", help="CSC명 (보고서 제목)")
    p.add_argument("--exclude", action="append", default=[], metavar="PATTERN",
                   help="제외할 파일 패턴 (여러 번 지정 가능)")
    p.add_argument("--encoding", help="소스 인코딩 (기본: UTF-8, 실패하면 CP949)")
    p.add_argument("--folder", action="store_true",
                   help="폴더에 프로젝트 파일이 있어도 쓰지 않고 폴더의 모든 소스(하위 폴더 포함)를 대상으로 함")
    p.add_argument("--version", action="version",
                   version=f"{NAME}({NAME_KO}) {VERSION_LABEL} · 명령 이름 srtgen · 따르는 기준: {criteria.MANUAL}")


def _check_sources(p: argparse.ArgumentParser, sources: List[Path]) -> None:
    for src in sources:
        if not src.exists():
            p.error(f"경로가 없습니다: {src}")


def _inputs(args: argparse.Namespace) -> List[Path]:
    """폴더를 주면, 그 폴더에 프로젝트 파일이 있으면 그것으로 연다 (--folder 이면 폴더 전체)."""
    sources, notes = resolve_inputs(args.sources, args.folder)
    for note in notes:
        print(f"[정보] {note}", file=sys.stderr)
    return sources


def _overrides(args: argparse.Namespace) -> Dict[str, Optional[str]]:
    return {"project": args.project, "csci": args.csci, "csc": args.csc}


def _report_info(args: argparse.Namespace, sources: List[Path]) -> Dict[str, str]:
    """보고서 제목: 명령줄 옵션 > 프로젝트 폴더의 srtgen.json > 기본값."""
    directory = settings.settings_dir(sources)
    info, warning = settings.resolve(directory, _overrides(args))
    if warning:
        print(f"[경고] {warning} 기본값을 씁니다.", file=sys.stderr)
    elif directory is not None and (directory / settings.FILE_NAME).is_file():
        print(f"[정보] 보고서 정보: {directory / settings.FILE_NAME}", file=sys.stderr)
    names = settings.placeholders(info)
    if names:
        print(f"[경고] 보고서 제목에 예시 값이 남아 있습니다({', '.join(names)}): "
              f"{report_heading(info['project'], info['csci'], info['csc'])}. "
              f"프로젝트 폴더의 {settings.FILE_NAME} 또는 --project, --csci, --csc 로 바꾸십시오.", file=sys.stderr)
    return info


def _serve(argv: List[str]) -> int:
    p = argparse.ArgumentParser(
        prog="srtgen serve",
        description=f"{NAME}: 예외사유를 브라우저에서 확인·편집하고 소스코드 주석에 반영한다 (이 PC 에서만 접속 가능).")
    _common(p, "*")
    p.add_argument("--port", type=int, default=int(os.environ["PORT"]) if os.environ.get("PORT", "").isdigit() else None,
                   help="접속 포트 (기본: 환경 변수 PORT, 없으면 8765 부터 비어 있는 포트)")
    p.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않음")
    p.add_argument("--rules", type=Path, metavar="FILE",
                   help="직접 넣는 규칙 번호·규칙명 목록 파일 (기본: 사용자 폴더의 .srtgen/rules.json)")
    p.add_argument("--projects", type=Path, metavar="FILE",
                   help="프로젝트 목록 파일 (기본: 사용자 폴더의 .srtgen/projects.json)")
    args = p.parse_args(argv)
    _check_sources(p, args.sources)
    sources = _inputs(args)
    from .server import App, serve
    try:
        app = App(sources, args.out, excludes=tuple(args.exclude), encoding=args.encoding, rules=args.rules,
                  overrides=_overrides(args), projects=args.projects)
    except ProjectError as e:
        p.error(str(e))
    serve(app, args.port, not args.no_browser)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if argv and argv[0] == "serve":
        return _serve(argv[1:])

    p = argparse.ArgumentParser(
        prog="srtgen",
        description=f"{NAME}({NAME_KO}): 소스코드 주석의 예외사유 표기법(SRT-...)으로 SW 신뢰성 시험 예외사유 보고서를 생성한다.",
        epilog="확인·편집용 웹 화면:  python -m srtgen serve <소스 경로> -o <출력 폴더>")
    _common(p)
    p.add_argument("--format", default="md,hwpx", help="출력 형식: md, hwpx 를 쉼표로 구분 (기본: md,hwpx)")
    p.add_argument("--code", choices=["text", "image"], default="text",
                   help="코드내용 표현: text(발췌), image(캡처 그림)")
    p.add_argument("--compact", action="store_true", help="hwpx 에서 예외사유마다 쪽을 나누지 않음")
    p.add_argument("--strict", action="store_true", help="경고가 있어도 실패(종료 코드 1)로 처리")
    p.add_argument("--issue", nargs="?", const="", metavar="메모",
                   help="만든 보고서를 새 판으로 보관하고 지난 판과 비교한 변경내역을 남김 (출력 폴더의 이력/)")
    args = p.parse_args(argv)

    formats = {f.strip().lower() for f in args.format.split(",") if f.strip()}
    unknown = formats - set(FORMATS)
    if unknown:
        p.error(f"알 수 없는 출력 형식: {', '.join(sorted(unknown))}")
    _check_sources(p, args.sources)
    if args.code == "image" and not codeimg.available():
        print("[경고] Pillow 가 없어 코드내용을 text 로 출력합니다", file=sys.stderr)

    sources = _inputs(args)
    info = _report_info(args, sources)
    try:
        workspace = open_paths(sources, args.exclude)
    except ProjectError as e:
        p.error(str(e))
    result = scan_entries(workspace.entries(), args.encoding)
    out = args.out or settings.out_dir(settings.settings_dir(sources))
    written = write_outputs(result, out, info["project"], info["csc"], formats, args.code, args.compact,
                            workspace.projects, csci=info["csci"])
    if args.issue is not None:
        title = report_heading(info["project"], info["csci"], info["csc"])
        try:
            version = history.issue(out, written, title, args.issue)
        except history.HistoryError as e:
            print(f"[오류] {e}", file=sys.stderr)
            return 1
        written.append(out / history.HISTORY_DIR / version["폴더"] / history.CHANGES_FILE)
        print("v{판} 으로 보관: 추가 {추가}건, 변경 {변경}건, 삭제 {삭제}건".format(판=version["판"], **version["변경"]))

    for proj in workspace.projects:
        for w in proj.warnings:
            print(f"[경고] {proj.name} ({proj.label}): {w}", file=sys.stderr)
    for d in result.diagnostics:
        print(d, file=sys.stderr)
    print(f"소스 {result.files_scanned}개 검사, 예외사유 {len(result.items)}건 "
          f"(발생 위치 {sum(i.count for i in result.items)}곳)")
    for path in written:
        print(f"  {path}")
    if result.has_errors or (args.strict and result.diagnostics):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
