"""예외사유를 확인·편집하는 로컬 웹 UI 서버.

이 PC(127.0.0.1)에서만 접속할 수 있다. 소스를 고치는 요청은 화면에 심어 둔 토큰이 있어야 하고,
Host 헤더가 다른 요청은 거부한다(다른 웹 페이지가 브라우저를 통해 소스를 고치지 못하게 한다).
"""
from __future__ import annotations

import atexit
import base64
import binascii
import json
import mimetypes
import os
import secrets
import shutil
import socket
import sys
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import about as about_info
from . import NAME, NAME_FULL, NAME_KO, VERSION_LABEL, __version__, codeimg, criteria, history, imageinfo, render_md, settings
from .forms import Builder, Options, report_heading
from .registry import Registry, key_of
from .registry import now as registry_now
from .registry import summary as registry_summary
from .generate import FORMATS, write_outputs
from .lexer import language_for
from .notation import TEST_TYPES
from .project import Node, ProjectError, Workspace, detect_projects, open_paths, project_kind, project_rank
from .scanner import Block, Diagnostic, ScanResult, scan_entries
from .writeback import (ATTACH_DIR, ATTACH_TYPES, Conflict, FieldEdit, WritebackError, apply_edits,
                        replace_comment, save_attachment)

def ask_directory(initial: str, title: str) -> str:
    """이 PC 의 폴더 선택 창(윈도우 탐색기 모양)을 띄워 고른 폴더를 돌려준다. 취소하면 빈 글.

    화면 서버는 이 PC(127.0.0.1)에서만 접속하므로 창은 사용자의 바탕화면에 뜬다. tkinter 가 없으면 예외.
    """
    import tkinter
    from tkinter import filedialog
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)      # 브라우저 뒤에 숨지 않게
    try:
        chosen = filedialog.askdirectory(parent=root, initialdir=initial or None, title=title, mustexist=True)
    finally:
        root.destroy()
    return str(Path(chosen)) if chosen else ""


def open_in_explorer(path: Path) -> None:
    """이 PC 의 파일 탐색기로 폴더를 연다(윈도우는 탐색기, 다른 OS 는 기본 파일 관리자).

    브라우저는 보안상 PC 의 폴더를 열 수 없으므로 서버가 연다. 서버는 127.0.0.1 에서만 받으므로 창은 사용자 PC 에 뜬다.
    """
    if os.name == "nt":
        os.startfile(str(path))
    else:
        import subprocess
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


WEB_DIR = Path(__file__).parent / "web"
# 화면(web/index.html 의 API_LEVEL)과 맞춰 올리는 번호. 화면은 요청마다 새로 읽지만 서버는 다시 띄워야 바뀌므로,
# 예전 서버가 남아 있으면 화면이 이 번호로 알아채고 "다시 실행하십시오"를 보인다. 상태의 모양을 바꾸면 둘 다 올린다.
API_LEVEL = 8
RULES_FILE = Path.home() / ".srtgen" / "rules.json"      # 사용자가 넣는 규칙 목록의 기본 위치
RULES_INFO_KEY = "_정보"            # 규칙 목록 파일 안에서 기준별 버전·출처를 두는 키 (목록이 아님)
RULES_FILE_MAX = 2 * 1024 * 1024    # 불러오는 규칙 목록 파일(CSV·TXT)의 최대 크기
MAX_BODY = 16 * 1024 * 1024       # 그림 올리기(10MB, base64)를 받을 수 있는 크기


class App:
    def __init__(self, sources: List[Path], out: Optional[Path] = None, project: Optional[str] = None,
                 csc: Optional[str] = None, excludes: Tuple[str, ...] = (), encoding: Optional[str] = None,
                 rules: Optional[Path] = None, csci: Optional[str] = None,
                 overrides: Optional[Dict[str, Optional[str]]] = None, projects: Optional[Path] = None):
        self.inputs = [Path(s) for s in sources]      # 연 폴더, 프로젝트 파일, 소스 파일
        self.rules_path = Path(rules) if rules else RULES_FILE    # 사용자가 넣는 규칙 번호·규칙명 목록
        self.registry = Registry(projects)            # 이 PC 에서 다룬 프로젝트 목록
        # 보고서 제목: 사업명, CSCI명, CSC명. 명령줄 값 > 프로젝트 폴더의 srtgen.json > 기본값
        # 출력 폴더: 명령줄 값 > 프로젝트 폴더의 srt_report (srtgen.json 의 "출력 폴더")
        # 명령줄 값은 처음 연 대상에만 쓴다. 다른 프로젝트를 열면 그 폴더의 값을 쓴다.
        given = dict(overrides or {})
        for key, val in (("project", project), ("csci", csci), ("csc", csc)):
            if val is not None:
                given.setdefault(key, val)
        self.project = self.csci = self.csc = ""
        self.info_error = ""
        self.out = Path()
        self.info_dir = self._load_info(given, Path(out) if out else None)
        self.excludes = tuple(excludes)
        self.encoding = encoding
        self.token = secrets.token_urlsafe(24)
        self.lock = threading.Lock()
        self.picking = threading.Lock()               # 폴더 선택 창은 한 번에 하나
        self.folder_picker = ask_directory            # 시험에서는 바꿔 끼운다
        self.folder_opener = open_in_explorer         # 출력 폴더를 탐색기로 연다. 시험에서는 바꿔 끼운다
        # 양식 미리보기가 쓰는 그림(첨부 복사본)은 출력 폴더가 아니라 이 임시 폴더에 둔다. 출력 폴더(srt_report/)는
        # 형상관리되므로 미리보기만 봐도 쓰이지 않는 그림이 남으면 안 된다. 서버가 끝나면 지운다.
        self.preview_dir = Path(tempfile.mkdtemp(prefix="srtgen_preview_"))
        atexit.register(shutil.rmtree, self.preview_dir, True)
        self.workspace = Workspace([])
        self.result: ScanResult = self.rescan()
        self._remember(opened=registry_now())

    def _load_info(self, overrides: Dict[str, Optional[str]], out: Optional[Path] = None) -> Optional[Path]:
        """보고서 정보와 출력 폴더를 연 대상의 srtgen.json 에서 읽는다. 그 폴더를 돌려준다."""
        directory = settings.settings_dir(self.inputs)
        values, self.info_error = settings.resolve(directory, overrides)
        self.project, self.csci, self.csc = values["project"], values["csci"], values["csc"]
        self.out = out or settings.out_dir(directory)
        return directory

    def _remember(self, **values) -> None:
        """프로젝트 목록에 지금 연 것을 넣거나 고친다."""
        if self.inputs:
            self.registry.touch(self.inputs, **registry_summary(self.project, self.csci, self.csc, self.info_dir,
                                                                self.result), **values)

    def remove_project(self, payload: dict) -> dict:
        """목록에서 뺀다. 프로젝트의 파일은 건드리지 않는다."""
        if not self.registry.remove(str(payload.get("key", ""))):
            raise WritebackError("목록에 없는 프로젝트입니다.")
        return {"state": self.state()}

    def set_info(self, payload: dict) -> dict:
        """보고서 정보를 연 대상의 srtgen.json 에 저장한다 (그 파일 하나만 쓴다)."""
        with self.lock:
            directory = settings.settings_dir(self.inputs)
            if directory is None:
                raise WritebackError("먼저 소스를 여십시오.")
            try:
                values = settings.clean(payload)
                settings.save(directory, values)
            except settings.SettingsError as e:
                raise WritebackError(str(e))
            self.project, self.csci, self.csc = values["project"], values["csci"], values["csc"]
            self.info_error = ""
            self._remember()
        return {"state": self.state()}

    def rescan(self) -> ScanResult:
        """프로젝트 파일을 다시 읽어 소스 구성을 만들고 표기법을 수집한다."""
        self.workspace = open_paths(self.inputs, self.excludes)
        self.result = scan_entries(self.workspace.entries(), self.encoding)
        self.stamp = self._stamp()
        return self.result

    def _stamp(self) -> Dict[str, Optional[Tuple[int, int]]]:
        """다시 읽어야 하는지 가리는 표시: 읽은 소스와 그 폴더, 연 대상, 프로젝트 파일(옆의 프로젝트 파일 포함)의
        수정 시각·크기. 폴더의 수정 시각은 그 안에 파일이 생기거나 지워지면 바뀐다."""
        paths = set(self.result.paths.values()) | set(self.inputs)
        paths |= {p.parent for p in self.result.paths.values()}
        for proj in self.workspace.projects:
            paths.add(proj.origin)
            folder = proj.origin if proj.origin.is_dir() else proj.origin.parent
            try:
                paths |= {c for c in folder.iterdir() if c.is_file() and project_kind(c.name)}
            except OSError:
                pass
        stamp: Dict[str, Optional[Tuple[int, int]]] = {}
        for p in paths:
            try:
                st = os.stat(p)
                stamp[str(p)] = (st.st_mtime_ns, st.st_size)
            except OSError:
                stamp[str(p)] = None
        return stamp

    def changed(self) -> bool:
        """마지막으로 읽은 뒤 소스나 프로젝트 파일이 바뀌었는가 (화면이 창으로 돌아올 때 묻는다)."""
        return bool(self.inputs) and self._stamp() != self.stamp

    def _node(self, node: Node) -> dict:
        if node.kind == "file":
            return {"n": node.name, "k": "f", "f": node.rel}
        return {"n": node.name, "k": "p" if node.kind == "project" else "g",
                "c": [self._node(c) for c in node.children]}

    # ---- 화면에 보낼 상태 ----
    def _block(self, b: Block) -> dict:
        return {"file": b.file, "sha": self.result.hashes.get(b.file, ""), "tag": b.tag, "test": b.test,
                "id": b.ex_id, "index": b.index, "ordinal": b.ordinal, "lines": b.lines,
                "tag_line": b.tag_line, "function": b.function, "language": b.language,
                "code": [[n, t] for n, t in b.code], "fields": b.fields, "editable": b.editable}

    def state(self) -> dict:
        r = self.result
        return {
            "version": __version__,
            "name": NAME, "name_full": NAME_FULL, "name_ko": NAME_KO,   # 보이는 이름
            "version_label": VERSION_LABEL,                              # 보이는 버전 (ver.0.01)
            "manual": criteria.MANUAL, "manual_edition": criteria.MANUAL_EDITION,   # 이 도구 버전이 따르는 매뉴얼
            "inputs": [str(s.resolve()) for s in self.inputs],
            "projects": [{"name": p.name, "label": p.label, "origin": str(p.origin), "warnings": p.warnings}
                         for p in self.workspace.projects],
            "tree": [self._node(p.root) for p in self.workspace.projects],
            "out": str(self.out.resolve()),
            "history": history.versions(self.out),            # 보관한 보고서 판 (오래된 것부터)
            "registry": self.registry.listing(),              # 이 PC 에서 다룬 프로젝트 목록
            "registry_path": str(self.registry.path),
            "current": key_of(self.inputs) if self.inputs else "",
            "project": self.project, "csci": self.csci, "csc": self.csc,
            "heading": report_heading(self.project, self.csci, self.csc),
            # 보고서 정보 파일(srtgen.json): 위치, 있는지, 읽을 수 없으면 그 까닭
            "info": {"file": str(self.info_dir / settings.FILE_NAME) if self.info_dir else "",
                     "saved": bool(self.info_dir and (self.info_dir / settings.FILE_NAME).is_file()),
                     "error": self.info_error, "defaults": settings.DEFAULTS,
                     # 아직 예시 값(OOO)인 항목: 보고서는 만들되 화면에서 알린다
                     "placeholders": settings.placeholders({"project": self.project, "csci": self.csci,
                                                            "csc": self.csc})},
            "image_available": codeimg.available(),
            "files_scanned": r.files_scanned, "files_with_tags": r.files_with_tags,
            "types": [{"code": t.code, "name": t.name, "title": t.title, "report": t.report,
                       "fields": [{"key": f.key, "required": f.required, "per_occurrence": f.per_occurrence,
                                   "help": f.help, "choices": list(f.choices)} for f in t.fields]}
                      for t in TEST_TYPES.values()],
            "items": [{"key": f"{i.test}:{i.ex_id}", "tag": i.tag, "test": i.test, "id": i.ex_id,
                       "count": i.count, "fields": i.fields,
                       "derived": {"FA내용": criteria.derived_content(i.test, i.fields)},
                       "occurrences": [{"main": self._block(o.main), "fields": o.fields,
                                        "refs": [self._block(x) for x in o.refs]} for o in i.occurrences]}
                      for i in r.items],
            "mermaid": (WEB_DIR / "vendor" / "mermaid.min.js").is_file(),
            # 코딩 규칙 기준별 규칙 번호 -> 규칙명 (화면에서 번호를 고르면 규칙명을 채운다)
            "rule_titles": self.rule_titles(),
            "user_rules": self.user_rules(),
            "builtin_rules": {name: len(rules) for name, rules in criteria.RULE_TITLES.items()},
            # '규칙 목록' 창에서 보는 도구에 든 목록(CWE 포함)과, 목록이 없는 기준의 까닭.
            # 규칙은 [번호, 이름] 쌍의 배열로 보낸다: 객체로 보내면 브라우저가 "1", "2" 같은 키를 앞으로 모아
            # Java 절 순서(1, 1.1, 1.2, 2 …)가 깨진다.
            "reference_lists": [{"group": g, "name": n, "rules": list(rules.items()), **info}
                                for g, n, rules, info in criteria.reference_lists()],
            "user_rule_info": self.user_rule_info(),       # 직접 넣은 목록의 버전·가져온 곳
            "rule_notes": criteria.RULE_LIST_NOTES,
            "api": API_LEVEL,
            "rules_path": str(self.rules_path),
            "diagnostics": [self._diagnostic(d) for d in r.diagnostics],
        }

    def _diagnostic(self, d: Diagnostic) -> dict:
        c = d.comment
        return {"level": d.level, "file": d.file, "line": d.line, "message": d.message, "item": d.item,
                "suggest": [list(s) for s in d.suggest], "sha": self.result.hashes.get(d.file, ""),
                "comment": c and {"cid": c.cid, "kind": c.kind, "line": c.line, "end_line": c.end_line,
                                  "raw": c.raw, "before": [list(x) for x in c.before],
                                  "after": [list(x) for x in c.after]}}

    # ---- 설정 ▸ 정보 ----
    def about(self) -> dict:
        """소프트웨어 정보와 오픈소스 정보(원본은 THIRD_PARTY.md)."""
        paths = {"규칙 목록 파일": str(self.rules_path), "프로젝트 목록 파일": str(self.registry.path)}
        return {"software": about_info.software(paths, (WEB_DIR / "vendor" / "mermaid.min.js").is_file()),
                **about_info.third_party()}

    # ---- 규칙 번호·규칙명 목록 ----
    def _rules_file(self) -> dict:
        """규칙 목록 파일: {기준: {번호: 규칙명}, "_정보": {기준: {"버전", "출처"}}}. 없거나 깨졌으면 빈 것."""
        try:
            data = json.loads(self.rules_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def user_rules(self) -> Dict[str, Dict[str, str]]:
        """사용자가 넣어 둔 목록. 파일이 없거나 형식이 다르면 빈 목록. "_"로 시작하는 키는 목록이 아니다."""
        return {str(k): {str(a): str(b) for a, b in v.items()}
                for k, v in self._rules_file().items() if isinstance(v, dict) and not str(k).startswith("_")}

    def user_rule_info(self) -> Dict[str, Dict[str, str]]:
        """직접 넣은 목록마다 사용자가 적은 버전(예: MISRA C:2012 AMD4)과 가져온 곳(URL·문서)."""
        info = self._rules_file().get(RULES_INFO_KEY)
        if not isinstance(info, dict):
            return {}
        return {str(k): {"버전": str(v.get("버전", "")), "출처": str(v.get("출처", ""))}
                for k, v in info.items() if isinstance(v, dict)}

    def parse_rules(self, payload: dict) -> dict:
        """화면이 올린 CSV·TXT 파일을 [번호, 규칙명] 목록으로 읽어 돌려준다. 저장은 하지 않는다(화면에서 확인 후 저장)."""
        name = str(payload.get("name", ""))
        try:
            raw = base64.b64decode(str(payload.get("data", "")), validate=True)
        except (binascii.Error, ValueError):
            raise WritebackError("잘못된 파일 내용입니다.")
        if len(raw) > RULES_FILE_MAX:
            raise WritebackError(f"파일이 너무 큽니다({len(raw):,}바이트). {RULES_FILE_MAX // 1024 // 1024}MB 이하만 받습니다.")
        try:
            return criteria.parse_rule_file(name, raw)
        except ValueError as e:
            raise WritebackError(str(e))

    def rule_titles(self) -> Dict[str, Dict[str, str]]:
        """고를 수 있는 규칙: 도구에 든 목록 + 연 소스에 이미 적힌 것 + 사용자가 넣은 것(뒤의 것이 우선)."""
        merged = {name: dict(rules) for name, rules in criteria.RULE_TITLES.items()}
        for item in self.result.items:
            if item.test != "S-C":
                continue
            f = item.fields
            standard = criteria.coding_standard(f.get("기준", "")) or f.get("기준", "").strip()
            rule, title = f.get("규칙", "").strip(), f.get("FA내용", "").split("\n")[0].strip()
            if standard and rule and title:
                merged.setdefault(standard, {}).setdefault(rule, title)
        for standard, rules in self.user_rules().items():
            merged.setdefault(standard, {}).update(rules)
        return merged

    def set_rules(self, payload: dict) -> dict:
        """코딩 규칙 기준 하나의 사용자 목록을 통째로 바꾼다 (한 줄에 "번호<탭>규칙명")."""
        raw = " ".join(str(payload.get("standard", "")).split())[:80]
        if not raw:
            raise WritebackError("코딩 규칙 기준을 고르십시오.")
        standard = criteria.coding_standard(raw) or raw
        if standard.startswith("_"):            # "_" 로 시작하는 키는 파일 안의 정보 자리다
            raise WritebackError("기준 이름은 \"_\"로 시작할 수 없습니다.")
        rules, bad = criteria.parse_rule_lines(str(payload.get("text", "")))
        if bad:
            raise WritebackError(f"{bad[0]}번째 줄을 번호와 규칙명으로 나눌 수 없습니다. "
                                 "\"번호<탭>규칙명\" 또는 \"번호: 규칙명\"으로 적으십시오.")
        version = " ".join(str(payload.get("version", "")).split())[:200]
        source = " ".join(str(payload.get("source", "")).split())[:500]
        with self.lock:
            data = self.user_rules()
            if rules:
                data[standard] = rules
            else:
                data.pop(standard, None)
            info = self.user_rule_info()
            if version or source:
                info[standard] = {"버전": version, "출처": source}
            else:
                info.pop(standard, None)
            if info:
                data[RULES_INFO_KEY] = info
            try:
                self.rules_path.parent.mkdir(parents=True, exist_ok=True)
                text = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
                self.rules_path.write_bytes(text.encode("utf-8"))      # 줄바꿈 \n 그대로 (Python 3.9 호환)
            except OSError as e:
                raise WritebackError(f"규칙 목록을 저장할 수 없습니다 ({e.strerror}): {self.rules_path}")
        return {"standard": standard, "count": len(rules), "state": self.state()}

    def _source(self, rel: str, sha: str) -> Path:
        """화면이 가리킨 소스 파일. 수집한 파일이고 화면이 본 내용 그대로일 때만 돌려준다."""
        path = self.result.paths.get(rel)
        if path is None:
            raise Conflict(f"{rel}: 수집한 소스에 없는 파일입니다. 소스를 다시 읽으십시오.")
        if not sha or sha != self.result.hashes.get(rel):
            raise Conflict(f"{rel}: 화면의 내용이 최신이 아닙니다. 소스를 다시 읽으십시오.")
        return path

    # ---- 잘못 쓴 표기법 주석 고치기 ----
    def fix(self, payload: dict) -> dict:
        rel = str(payload["file"])
        with self.lock:
            path = self._source(rel, str(payload.get("sha", "")))
            try:
                replace_comment(path, rel, language_for(rel), int(payload["cid"]), str(payload["before"]),
                                str(payload["text"]), str(payload["sha"]))
            finally:
                self.rescan()
        return {"saved": [rel], "state": self.state()}

    # ---- 근거자료(그림, 다이어그램) ----
    def attach(self, payload: dict) -> dict:
        """그림이나 다이어그램 원본을 소스 파일 옆 srt_attach 폴더에 저장한다. 주석은 건드리지 않는다."""
        rel = str(payload["file"])
        path = self.result.paths.get(rel)
        if path is None:
            raise Conflict(f"{rel}: 수집한 소스에 없는 파일입니다. 소스를 다시 읽으십시오.")
        try:
            data = base64.b64decode(str(payload["data"]), validate=True)
        except (binascii.Error, ValueError):
            raise WritebackError("잘못된 파일 내용입니다.")
        name = str(payload["name"])
        if payload.get("dpi") and name.lower().endswith(".png"):
            data = imageinfo.with_dpi(data, int(payload["dpi"]))
        with self.lock:
            return {"path": save_attachment(path, name, data, bool(payload.get("overwrite")))}

    def attachment(self, rel: str, ref: str) -> Optional[Path]:
        """@첨부 가 가리키는 파일. 그 소스가 실제로 참조하거나 srt_attach 폴더에 있는 것만 내준다."""
        source = self.result.paths.get(rel)
        if source is None or Path(ref).suffix.lower() not in ATTACH_TYPES:
            return None
        target = (source.parent / ref).resolve()
        referenced = set()
        for item in self.result.items:
            for occ in item.occurrences:
                for block in [occ.main] + occ.refs:
                    if block.file == rel:
                        referenced.update(e.split("|")[0].strip()
                                          for e in block.fields.get("첨부", "").replace("\n", ";").split(";"))
        inside = target.parent == (source.parent / ATTACH_DIR).resolve()
        return target if target.is_file() and (inside or ref in referenced) else None

    # ---- 소스에 반영 ----
    def save(self, payload: dict) -> dict:
        by_file: Dict[str, Tuple[str, List[FieldEdit]]] = {}
        for e in payload.get("edits", []):
            fields = e.get("fields")
            if not isinstance(fields, dict) or not all(isinstance(v, str) for v in fields.values()):
                raise WritebackError("잘못된 요청입니다.")
            edit = FieldEdit(str(e["test"]), int(e["id"]), int(e["index"]), int(e["ordinal"]), fields)
            by_file.setdefault(str(e["file"]), (str(e.get("sha", "")), []))[1].append(edit)
        if not by_file:
            raise WritebackError("반영할 내용이 없습니다.")
        with self.lock:
            # 화면이 읽은 뒤에 바뀐 파일이 하나라도 있으면 아무것도 쓰지 않는다
            for rel, (sha, _edits) in by_file.items():
                self._source(rel, sha)
            done: List[str] = []
            try:
                for rel, (sha, edits) in by_file.items():
                    apply_edits(self.result.paths[rel], rel, language_for(rel), edits, sha)
                    done.append(rel)
            finally:
                self.rescan()
        return {"saved": done, "state": self.state()}

    # ---- 소스 열기 ----
    def open(self, payload: dict) -> dict:
        paths = list(dict.fromkeys(Path(str(p)) for p in payload.get("paths", [])))
        if not paths:
            raise WritebackError("열 대상을 고르십시오.")
        with self.lock:
            previous = self.inputs
            self.inputs = previous + [p for p in paths if p not in previous] if payload.get("add") else paths
            try:
                self.rescan()
            except ProjectError as e:
                self.inputs = previous
                self.rescan()
                raise WritebackError(str(e))
            if settings.settings_dir(self.inputs) != self.info_dir:    # 다른 프로젝트: 그 폴더의 보고서 정보
                self.info_dir = self._load_info({})
            self._remember(opened=registry_now())
        return {"state": self.state()}

    def pick_folder(self, payload: dict) -> dict:
        """폴더 선택 창을 띄운다. 한 번에 하나만 띄운다."""
        if not self.picking.acquire(blocking=False):
            raise WritebackError("폴더 선택 창이 이미 열려 있습니다. 작업 표시줄에서 그 창을 찾아 주십시오.")
        try:
            initial = str(payload.get("initial") or "")
            if not initial and self.inputs:
                first = self.inputs[0].resolve()
                initial = str(first if first.is_dir() else first.parent)
            try:
                path = self.folder_picker(initial if os.path.isdir(initial) else "", "보고서를 만들 소스 폴더 선택")
            except Exception as e:      # tkinter 가 없거나 창을 띄울 수 없는 환경
                raise WritebackError(f"이 PC 에서는 폴더 선택 창을 띄울 수 없습니다 ({type(e).__name__}). "
                                     "목록에서 고르십시오.")
        finally:
            self.picking.release()
        return {"path": path}

    def open_folder(self, payload: dict) -> dict:
        """출력 폴더(또는 그 아래 폴더, 예: 이력/v1_…)를 탐색기로 연다. 출력 폴더 밖은 열지 않는다."""
        rel = str(payload.get("path") or "").replace("\\", "/").strip("/")
        root = self.out.resolve()
        target = (root / rel).resolve() if rel else root
        if target != root and root not in target.parents:
            raise WritebackError("출력 폴더 밖은 열 수 없습니다.")
        if not target.is_dir():
            raise WritebackError("출력 폴더가 아직 없습니다. 보고서를 만들면 생깁니다." if target == root
                                 else f"폴더가 없습니다: {rel}")
        try:
            self.folder_opener(target)
        except Exception as e:      # 탐색기를 띄울 수 없는 환경
            raise WritebackError(f"탐색기를 열 수 없습니다 ({type(e).__name__}). 경로를 복사해 여십시오: {target}")
        return {"path": str(target)}

    def browse(self, payload: dict) -> dict:
        """열기 대화상자용: 폴더 안의 폴더, 프로젝트 파일, 소스 파일을 돌려준다."""
        wanted = str(payload.get("dir") or "")
        if wanted == "::roots":
            drives = (os.listdrives() if hasattr(os, "listdrives")
                      else [f"{c}:\\" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{c}:\\")])
            return {"dir": "", "parent": None, "entries": [
                {"name": d, "path": d, "type": "dir"} for d in (drives if os.name == "nt" else ["/"])]}
        if not wanted:
            start = self.inputs[0].resolve() if self.inputs else Path.cwd()
            wanted = str(start if start.is_dir() else start.parent)
        folder = Path(wanted)
        if not folder.is_dir():
            raise WritebackError(f"폴더가 없습니다: {wanted}")
        folder = folder.resolve()
        entries = []
        detected = set(detect_projects(folder))        # "이 폴더 열기"를 누르면 권할 프로젝트 파일
        try:
            children = sorted(os.scandir(folder), key=lambda e: e.name.lower())
        except OSError as e:
            raise WritebackError(f"폴더를 읽을 수 없습니다: {e.strerror}")
        for child in children:
            try:
                is_dir = child.is_dir()
            except OSError:
                continue
            if is_dir:
                if not child.name.startswith((".", "$")):
                    entries.append({"name": child.name, "path": child.path, "type": "dir"})
            elif project_kind(child.name):
                # rank: 폴더를 열 때 대표가 될 수 있는 순위 (None 이면 직접 골라야만 쓰는 파일, 예: *.mk)
                entries.append({"name": child.name, "path": child.path, "type": "project",
                                "label": project_kind(child.name), "rank": project_rank(child.name),
                                "detected": Path(child.path) in detected})
            elif language_for(child.name):
                entries.append({"name": child.name, "path": child.path, "type": "source"})
        order = {"dir": 0, "project": 1, "source": 2}
        entries.sort(key=lambda e: order[e["type"]])
        parent = "::roots" if folder.parent == folder else str(folder.parent)
        return {"dir": str(folder), "parent": parent, "entries": entries}

    # ---- 산출물 ----
    def generate(self, payload: dict) -> dict:
        formats = [f for f in payload.get("formats", FORMATS) if f in FORMATS]
        if not formats:
            raise WritebackError("출력 형식을 하나 이상 고르십시오.")
        with self.lock:
            self.project = str(payload.get("project") or self.project)
            if "csci" in payload:                     # CSCI명은 비워 둘 수 있다 (제목에서 빠진다)
                self.csci = str(payload.get("csci") or "")
            self.csc = str(payload.get("csc") or self.csc)
            result = self.rescan()
            code_mode = "image" if payload.get("code") == "image" else "text"
            try:
                written = write_outputs(result, self.out, self.project, self.csc, formats, code_mode,
                                        bool(payload.get("compact")), self.workspace.projects, csci=self.csci)
            except OSError as e:
                raise WritebackError(f"보고서를 쓸 수 없습니다 ({e.strerror}): {self.out}")
            title = report_heading(self.project, self.csci, self.csc)
            # 지난 판과 비교 (판으로 보관하지 않아도 보여 준다)
            current = json.loads((self.out / history.DATA_FILE).read_text(encoding="utf-8"))
            changes = history.counts(history.compare(history.last_data(self.out), current))
            version = None
            if payload.get("issue"):
                try:
                    version = history.issue(self.out, written, title, str(payload.get("note") or "")[:500])
                except history.HistoryError as e:
                    raise WritebackError(str(e))
            vs = history.versions(self.out)
            self._remember(generated=registry_now(), version=vs[-1]["판"] if vs else 0)
        files = [{"name": p.relative_to(self.out).as_posix(), "size": p.stat().st_size} for p in written]
        if version:
            folder = f"{history.HISTORY_DIR}/{version['폴더']}"
            files.append({"name": f"{folder}/{history.CHANGES_FILE}",
                          "size": (self.out / folder / history.CHANGES_FILE).stat().st_size})
        return {"files": files, "out": str(self.out.resolve()), "state": self.state(), "version": version,
                "changes": changes, "errors": sum(1 for d in result.diagnostics if d.level == "error")}

    def preview(self, key: str) -> str:
        """예외사유 하나를 양식 모양의 HTML 로 돌려준다 (소스에 저장된 내용 기준)."""
        with self.lock:
            item = next((i for i in self.result.items if f"{i.test}:{i.ex_id}" == key), None)
            if item is None:
                return "<p>예외사유를 찾을 수 없습니다.</p>"
            # 그림은 미리보기 전용 임시 폴더에 복사한다(출력 폴더에 쓰지 않는다). 화면은 /images/ 로 받는다.
            builder = Builder(Options(project=self.project, csci=self.csci, csc=self.csc, out_dir=self.preview_dir))
            report = builder.report(item.test, [item])
        title = "<br>".join(render_md._esc(t) for t in report.title)
        notes = "".join(f"<p class='note'>{render_md._esc(n)}</p>" for n in report.notes)
        return (f"<h3 class='form-title'>{title}</h3>"
                + render_md._table(report.sections[0].table, self.preview_dir) + notes)


class Handler(BaseHTTPRequestHandler):
    app: App
    server_version = "srtgen"

    def log_message(self, fmt: str, *args) -> None:   # 요청 기록은 남기지 않는다
        pass

    def _send(self, status: int, body: bytes, ctype: str, extra: Optional[Dict[str, str]] = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: dict) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _host_ok(self) -> bool:
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _file(self, base: Path, rel: str) -> None:
        try:
            path = (base / rel).resolve()
            path.relative_to(base.resolve())
        except (ValueError, OSError):
            return self._json(404, {"error": "없는 경로입니다."})
        if not path.is_file():
            return self._json(404, {"error": "없는 파일입니다."})
        suffix = path.suffix.lower()
        if suffix in (".md", ".json", ".txt"):
            ctype = "text/plain; charset=utf-8"
        elif suffix == ".js":            # 윈도우 레지스트리의 형식 설정에 기대지 않는다
            ctype = "text/javascript; charset=utf-8"
        else:
            ctype = mimetypes.types_map.get(suffix, "application/octet-stream")
        extra = {}
        if suffix == ".hwpx":
            extra["Content-Disposition"] = "attachment; filename*=UTF-8''" + urllib.parse.quote(path.name)
        self._send(200, path.read_bytes(), ctype, extra)

    def do_GET(self) -> None:
        if not self._host_ok():
            return self._json(403, {"error": "허용하지 않는 주소입니다."})
        url = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(url.path)
        if path == "/":
            page = (WEB_DIR / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", self.app.token)
            return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        if path == "/api/state":
            return self._json(200, self.app.state())
        if path == "/api/changed":
            return self._json(200, {"changed": self.app.changed()})
        if path == "/api/about":                    # 설정 ▸ 정보 (읽기만 한다)
            return self._json(200, self.app.about())
        if path == "/api/doc":                      # 고지 전문 등 정해진 문서만 (about.document)
            text = about_info.document(urllib.parse.parse_qs(url.query).get("name", [""])[0])
            if text is None:
                return self._json(404, {"error": "없는 문서입니다."})
            return self._send(200, text.encode("utf-8"), "text/plain; charset=utf-8")
        if path == "/api/preview":
            key = urllib.parse.parse_qs(url.query).get("key", [""])[0]
            return self._send(200, self.app.preview(key).encode("utf-8"), "text/html; charset=utf-8")
        if path == "/api/attachment":
            query = urllib.parse.parse_qs(url.query)
            target = self.app.attachment(query.get("file", [""])[0], query.get("path", [""])[0])
            if target is None:
                return self._json(404, {"error": "없는 파일입니다."})
            ctype = ("text/plain; charset=utf-8" if target.suffix.lower() == ".mmd"
                     else imageinfo.media_type(target) or "application/octet-stream")
            return self._send(200, target.read_bytes(), ctype)
        if path.startswith("/vendor/"):          # 함께 배포하는 외부 스크립트 (THIRD_PARTY.md)
            return self._file(WEB_DIR / "vendor", path[len("/vendor/"):])
        if path.startswith("/out/"):
            return self._file(self.app.out, path[len("/out/"):])
        if path.startswith("/images/"):          # 양식 미리보기 안의 그림 (미리보기 전용 임시 폴더)
            return self._file(self.app.preview_dir / "images", path[len("/images/"):])
        self._json(404, {"error": "없는 주소입니다."})

    def do_POST(self) -> None:
        if not self._host_ok() or not secrets.compare_digest(
                self.headers.get("X-SRT-Token", ""), self.app.token):
            return self._json(403, {"error": "허용하지 않는 요청입니다. 화면을 새로 고치십시오."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= MAX_BODY:
                return self._json(413, {"error": "요청이 너무 큽니다."})
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            return self._json(400, {"error": "잘못된 요청입니다."})
        try:
            if self.path == "/api/save":
                return self._json(200, self.app.save(payload))
            if self.path == "/api/generate":
                return self._json(200, self.app.generate(payload))
            if self.path == "/api/rules":
                return self._json(200, self.app.set_rules(payload))
            if self.path == "/api/rules/parse":
                return self._json(200, self.app.parse_rules(payload))
            if self.path == "/api/report-info":
                return self._json(200, self.app.set_info(payload))
            if self.path == "/api/projects/remove":
                return self._json(200, self.app.remove_project(payload))
            if self.path == "/api/fix":
                return self._json(200, self.app.fix(payload))
            if self.path == "/api/attach":
                return self._json(200, self.app.attach(payload))
            if self.path == "/api/open":
                return self._json(200, self.app.open(payload))
            if self.path == "/api/pick-folder":
                return self._json(200, self.app.pick_folder(payload))
            if self.path == "/api/open-folder":
                return self._json(200, self.app.open_folder(payload))
            if self.path == "/api/browse":
                return self._json(200, self.app.browse(payload))
            if self.path == "/api/rescan":
                with self.app.lock:
                    try:
                        self.app.rescan()
                    except ProjectError as e:
                        raise WritebackError(str(e))
                return self._json(200, {"state": self.app.state()})
        except Conflict as e:
            return self._json(409, {"error": str(e), "state": self.app.state()})
        except (WritebackError, ProjectError) as e:
            return self._json(422, {"error": str(e), "state": self.app.state()})
        except (KeyError, TypeError, ValueError):
            return self._json(400, {"error": "잘못된 요청입니다."})
        self._json(404, {"error": "없는 주소입니다."})


class _Server(ThreadingHTTPServer):
    """다른 프로그램이 쓰는 포트에 함께 붙지 않는 서버.

    표준 HTTPServer 는 SO_REUSEADDR 를 켜는데, 윈도우에서는 이것이 이미 듣고 있는 포트에도 bind 를 허락한다.
    그러면 같은 PC 의 다른 도구(8765 를 쓰는 기술문서 작성 도구 등)와 포트를 나눠 갖게 되어 요청이 그쪽으로 간다.
    윈도우에서는 SO_EXCLUSIVEADDRUSE 로 포트를 혼자 쓰고, 다른 OS 에서는 SO_REUSEADDR 가 듣는 포트를 빼앗지 않으므로
    표준대로 둔다(다시 띄울 때 TIME_WAIT 에 막히지 않게).
    """
    allow_reuse_address = os.name != "nt"
    daemon_threads = True

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(app: App, port: int = 8765) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"app": app})
    return _Server(("127.0.0.1", port), handler)


def bind(app: App, port: Optional[int] = None) -> ThreadingHTTPServer:
    """port 를 주면 그 포트, 주지 않으면 8765 부터 비어 있는 포트에 연다."""
    if port is not None:
        return make_server(app, port)
    for candidate in range(8765, 8785):
        try:
            return make_server(app, candidate)
        except OSError:
            continue
    raise SystemExit("8765~8784 포트를 모두 쓰고 있습니다. --port 로 지정하십시오.")


def serve(app: App, port: Optional[int] = None, open_browser: bool = True) -> None:
    """port 를 주지 않으면 8765 부터 비어 있는 포트를 찾는다."""
    httpd = bind(app, port)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"{NAME}({NAME_KO}) {VERSION_LABEL} 화면: {url}  (끝내려면 Ctrl+C)", flush=True)
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
