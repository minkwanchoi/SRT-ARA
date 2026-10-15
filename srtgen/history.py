"""보고서 판 이력: 만든 보고서를 판(v1, v2, …)으로 보관하고 지난 판과 비교한다.

출력 폴더(기본 <프로젝트 폴더>/srt_report)의 맨 위에는 늘 마지막으로 만든 보고서가 있고, 판으로 보관하면
이력/v<번호>_<날짜-시각>/ 에 그 묶음을 복사하고 지난 판과 비교한 변경내역.md 를 함께 둔다.
판 목록은 이력/이력.json 이다. 모두 출력 폴더 안의 파일이라 소스와 함께 형상관리된다.

비교는 산출물의 exceptions.json 끼리 한다. 예외사유는 (시험 유형, ID)로 짝짓고, 줄 번호만 바뀐 것은
변경으로 보지 않는다(소스를 고치면 줄이 밀리기 때문이다).
"""
from __future__ import annotations

import datetime
import json
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from . import NAME

HISTORY_DIR = "이력"
INDEX_FILE = "이력.json"
CHANGES_FILE = "변경내역.md"
DATA_FILE = "exceptions.json"


class HistoryError(Exception):
    pass


def versions(out: Path) -> List[dict]:
    """보관한 판 목록 (오래된 것부터). 목록 파일이 없거나 읽을 수 없으면 빈 목록."""
    try:
        data = json.loads((out / HISTORY_DIR / INDEX_FILE).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    return [v for v in data.get("판", []) if isinstance(v, dict)] if isinstance(data, dict) else []


def _load(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def last_data(out: Path) -> Optional[dict]:
    """마지막 판의 exceptions.json."""
    vs = versions(out)
    return _load(out / HISTORY_DIR / vs[-1]["폴더"] / DATA_FILE) if vs else None


def _key(e: dict) -> str:
    return f"{e.get('test')}:{e.get('id')}"


def _occurrences(e: dict) -> List[dict]:
    return sorted(e.get("occurrences", []), key=lambda o: (o.get("file", ""), o.get("function", "")))


def _places(e: dict) -> List[tuple]:
    """발생 위치(파일, 함수). 줄 번호는 넣지 않는다."""
    return [(o.get("file", ""), o.get("function", "")) for o in _occurrences(e)]


def _changed_fields(a: dict, b: dict) -> set:
    return {f for f in set(a) | set(b) if a.get(f, "") != b.get(f, "")}


def _code(e: dict) -> List[tuple]:
    return sorted((o.get("file", ""), tuple(c.get("text", "") for c in o.get("code", [])))
                  for o in e.get("occurrences", []))


def compare(old: Optional[dict], new: dict) -> Dict[str, list]:
    """두 exceptions.json 의 차이: 추가, 삭제, 변경(무엇이 바뀌었는지). old 가 없으면 모두 추가."""
    before = {_key(e): e for e in (old or {}).get("exceptions", [])}
    after = {_key(e): e for e in new.get("exceptions", [])}
    added = [after[k] for k in after if k not in before]
    removed = [before[k] for k in before if k not in after]
    changed = []
    for k in after:
        if k not in before:
            continue
        a, b = before[k], after[k]
        what = []
        fields = _changed_fields(a.get("fields", {}), b.get("fields", {}))
        if _places(a) == _places(b):            # 위치별 항목(비고, 측정값 등)도 본다
            for oa, ob in zip(_occurrences(a), _occurrences(b)):
                fields |= _changed_fields(oa.get("fields", {}), ob.get("fields", {}))
        if fields:
            what.append("내용(" + ", ".join(sorted(fields)) + ")")
        if a.get("count") != b.get("count"):
            what.append(f"개수 {a.get('count')}→{b.get('count')}")
        elif _places(a) != _places(b):
            what.append("발생 위치")
        if _code(a) != _code(b):
            what.append("코드")
        if what:
            changed.append({"tag": b.get("tag", k), "test_name": b.get("test_name", ""), "what": what})
    return {"added": added, "removed": removed, "changed": changed}


def counts(diff: Dict[str, list]) -> Dict[str, int]:
    return {"추가": len(diff["added"]), "변경": len(diff["changed"]), "삭제": len(diff["removed"])}


def basis_of(data: Optional[dict]) -> Dict[str, str]:
    """exceptions.json 에 적힌 기준(매뉴얼 판, 도구 버전). 기준을 적기 전에 만든 판이면 빈 값."""
    b = (data or {}).get("기준")
    return {k: str(b.get(k, "")) for k in ("매뉴얼", "매뉴얼 판", "도구 버전")} if isinstance(b, dict) else \
        {"매뉴얼": "", "매뉴얼 판": "", "도구 버전": ""}


def render_changes(diff: Dict[str, list], title: str, label: str, previous: Optional[dict],
                   new_basis: Optional[Dict[str, str]] = None, old_basis: Optional[Dict[str, str]] = None) -> str:
    since = f"v{previous['판']} ({previous['시각']}) 대비" if previous else "첫 판"
    lines = [f"# {title} 예외사유 변경내역", "", f"- 판: {label}", f"- 비교: {since}",
             "- 추가 {추가}건, 변경 {변경}건, 삭제 {삭제}건".format(**counts(diff))]
    if new_basis and new_basis.get("매뉴얼"):
        lines.append(f"- 시험 기준: {new_basis['매뉴얼']} ({NAME} ver.{new_basis.get('도구 버전', '')})")
    # 매뉴얼이 개정되어 지난 판과 기준이 다르면 알린다 (점검 결과·양식이 기준 때문에 달라졌을 수 있다)
    if previous and new_basis and old_basis is not None and old_basis.get("매뉴얼 판") != new_basis.get("매뉴얼 판"):
        lines.append(f"- ⚠ 시험 기준이 바뀌었다: {old_basis.get('매뉴얼 판') or '(기록 없음)'} → {new_basis.get('매뉴얼 판')}. "
                     "기준이 달라 생긴 차이가 섞여 있을 수 있다.")
    lines += ["",
             "| 구분 | 식별자 | 시험 종류 | 바뀐 것 |", "|---|---|---|---|"]
    rows = ([("추가", e.get("tag", ""), e.get("test_name", ""), "") for e in diff["added"]]
            + [("변경", c["tag"], c["test_name"], ", ".join(c["what"])) for c in diff["changed"]]
            + [("삭제", e.get("tag", ""), e.get("test_name", ""), "") for e in diff["removed"]])
    lines += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in rows] or ["| - | 바뀐 예외사유 없음 | | |"]
    lines += ["", "※ 줄 번호만 바뀐 것은 변경으로 보지 않는다(주석 식별자로 위치를 찾는다).", ""]
    return "\n".join(lines)


def issue(out: Path, written: Sequence[Path], title: str, note: str = "",
          now: Optional[datetime.datetime] = None) -> dict:
    """방금 만든 보고서 묶음을 새 판으로 보관한다. 판 정보를 돌려준다."""
    now = now or datetime.datetime.now()
    history = out / HISTORY_DIR
    vs = versions(out)
    if (history / INDEX_FILE).exists() and not vs and _load(history / INDEX_FILE) is None:
        raise HistoryError(f"{history / INDEX_FILE}: 판 목록을 읽을 수 없습니다. 파일을 확인하십시오.")
    number = max([int(v.get("판", 0)) for v in vs] + [0]) + 1
    stamp = now.strftime("%Y%m%d-%H%M%S")
    folder = f"v{number}_{stamp}"
    target = history / folder
    new = _load(out / DATA_FILE) or {"exceptions": []}
    previous = vs[-1] if vs else None
    old = last_data(out)
    diff = compare(old, new)
    new_basis = basis_of(new)
    try:
        target.mkdir(parents=True)
        for path in written:
            shutil.copy2(path, target / path.name)
        if (out / "images").is_dir():
            shutil.copytree(out / "images", target / "images")
        # 줄바꿈은 \n 그대로 쓴다 (write_text 의 newline 인자는 Python 3.10 부터라 바이트로 쓴다)
        (target / CHANGES_FILE).write_bytes(
            render_changes(diff, title, f"v{number} ({now:%Y-%m-%d %H:%M})", previous, new_basis, basis_of(old))
            .encode("utf-8"))
        entry = {"판": number, "폴더": folder, "시각": now.strftime("%Y-%m-%d %H:%M"), "메모": note.strip(),
                 "제목": title,
                 # 어느 매뉴얼 판·도구 버전으로 만든 판인지 (매뉴얼 개정 뒤에도 알 수 있게)
                 "매뉴얼 판": new_basis["매뉴얼 판"], "도구 버전": new_basis["도구 버전"],
                 "예외사유": len(new.get("exceptions", [])),
                 "발생 위치": sum(int(e.get("count", 0)) for e in new.get("exceptions", [])),
                 "오류": sum(1 for d in new.get("diagnostics", []) if d.get("level") == "error"),
                 "변경": counts(diff)}
        index = {"판": vs + [entry]}
        (history / INDEX_FILE).write_bytes((json.dumps(index, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    except OSError as e:
        raise HistoryError(f"판을 보관할 수 없습니다 ({e.strerror}): {target}")
    return entry
