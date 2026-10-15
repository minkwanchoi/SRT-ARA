"""프로젝트 목록: 이 PC 의 개발자가 열어 본 프로젝트. 사용자 폴더의 .srtgen/projects.json 에 둔다.

개발자 한 사람이 여러 사업·프로젝트를 맡으므로 화면에서 연 프로젝트를 자동으로 넣고, 사업명 → CSCI명 → CSC명으로
묶어 보인다. 목록은 바로 가기일 뿐이다: 빼도 프로젝트의 파일은 그대로이고, 원본은 늘 프로젝트 폴더에 있다.
"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence

PROJECTS_FILE = Path.home() / ".srtgen" / "projects.json"
MAX_ENTRIES = 200


def key_of(inputs: Sequence[Path]) -> str:
    """연 대상(폴더, 프로젝트 파일, 소스 파일)으로 정한 식별자. 대소문자는 윈도우처럼 구분하지 않는다."""
    return "|".join(os.path.normcase(str(Path(p).resolve())) for p in inputs)


class Registry:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else PROJECTS_FILE

    def entries(self) -> List[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return []
        items = data.get("projects", []) if isinstance(data, dict) else []
        return [e for e in items if isinstance(e, dict) and e.get("key") and isinstance(e.get("inputs"), list)]

    def _write(self, entries: List[dict]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            text = json.dumps({"projects": entries[:MAX_ENTRIES]}, ensure_ascii=False, indent=1) + "\n"
            self.path.write_bytes(text.encode("utf-8"))      # 줄바꿈 \n 그대로 (Python 3.9 호환)
        except OSError:
            pass            # 목록은 편의 기능이다: 못 써도 작업은 계속한다

    def touch(self, inputs: Sequence[Path], **values) -> None:
        """목록에 넣거나 고친다. 최근에 다룬 것이 앞에 온다."""
        if not inputs:
            return
        key = key_of(inputs)
        entries = self.entries()
        entry = next((e for e in entries if e["key"] == key), {"key": key})
        entries = [e for e in entries if e["key"] != key]
        entry["inputs"] = [str(Path(p).resolve()) for p in inputs]
        entry.update(values)
        entry.setdefault("opened", now())
        entries.insert(0, entry)
        self._write(entries)

    def remove(self, key: str) -> bool:
        entries = self.entries()
        kept = [e for e in entries if e["key"] != key]
        if len(kept) == len(entries):
            return False
        self._write(kept)
        return True

    def listing(self) -> List[dict]:
        """화면에 보낼 목록: 대상이 아직 있는지 함께. 값은 정해진 모양으로 고른다(개수·판 번호는 정수, 나머지는 글).
        목록 파일은 사용자 폴더에 있지만 판 번호 등은 프로젝트 쪽 파일에서 옮겨 온 값이므로 그대로 믿지 않는다."""
        out = []
        for e in self.entries():
            clean = {"key": str(e["key"]), "inputs": [str(p) for p in e["inputs"]]}
            clean.update({k: str(e[k]) for k in _TEXT_KEYS if k in e and e[k] is not None})
            clean.update({k: _count(e.get(k)) for k in _COUNT_KEYS})
            clean["exists"] = all(Path(p).exists() for p in clean["inputs"])
            out.append(clean)
        return out


_TEXT_KEYS = ("project", "csci", "csc", "folder", "opened", "generated")
_COUNT_KEYS = ("items", "occurrences", "errors", "version")


def _count(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def summary(project: str, csci: str, csc: str, folder: Optional[Path], result) -> Dict[str, object]:
    """목록에 적을 값: 보고서 정보, 프로젝트 폴더, 예외사유·오류 수."""
    return {"project": project, "csci": csci, "csc": csc, "folder": str(folder) if folder else "",
            "items": len(result.items), "occurrences": sum(i.count for i in result.items),
            "errors": sum(1 for d in result.diagnostics if d.level == "error")}
