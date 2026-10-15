"""보고서 정보: 보고서 제목에 쓰는 사업명, CSCI명, CSC명.

연 프로젝트 파일이 있는 폴더(폴더를 열었으면 그 폴더)의 srtgen.json 에 둔다. 소스와 함께 형상관리하면
다른 PC, 다른 사람이 만들어도 같은 제목이 나오고, 명령줄과 화면이 같은 값을 쓴다.
값을 정하는 순서: 명령줄 옵션 > srtgen.json > 기본값(양식 예시의 OOO).

    {
      "사업명": "OOO체계개발사업",
      "CSCI명": "OOOO분석장치",
      "CSC명": "운용 CSC"
    }
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

FILE_NAME = "srtgen.json"
# 프로그램 안의 이름 -> 파일에 적는 이름
KEYS = {"project": "사업명", "csci": "CSCI명", "csc": "CSC명"}
DEFAULTS = {"project": "OOO체계개발사업", "csci": "OOOO분석장치", "csc": "OOOO CSC"}
MAX_LEN = 200
OUT_KEY = "출력 폴더"           # 적지 않으면 DEFAULT_OUT. 화면에서는 고치지 않고 파일에서만 바꾼다
DEFAULT_OUT = "srt_report"


class SettingsError(Exception):
    pass


def settings_dir(inputs: Sequence[Path]) -> Optional[Path]:
    """보고서 정보를 둘 폴더: 처음 연 대상이 폴더면 그 폴더, 파일(프로젝트 파일, 소스)이면 그 파일의 폴더."""
    if not inputs:
        return None
    first = Path(inputs[0]).resolve()
    return first if first.is_dir() else first.parent


def _read(path: Path) -> Dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as e:
        raise SettingsError(f"{path}: 읽을 수 없습니다 ({e.strerror}).")
    except ValueError as e:
        raise SettingsError(f"{path}: JSON 형식이 아닙니다 ({e}).")
    if not isinstance(data, dict):
        raise SettingsError(f"{path}: {{ \"사업명\": … }} 모양이어야 합니다.")
    return data


def load(directory: Optional[Path]) -> Tuple[Dict[str, str], bool]:
    """(파일에 적힌 값, 파일이 있는지). 값은 적힌 것만 돌려준다."""
    if directory is None:
        return {}, False
    path = directory / FILE_NAME
    if not path.is_file():
        return {}, False
    data = _read(path)
    values = {key: str(data[name]).strip() for key, name in KEYS.items()
              if isinstance(data.get(name), (str, int, float))}
    return values, True


def clean(values: Dict[str, object]) -> Dict[str, str]:
    """화면·요청에서 받은 값을 고른다. 사업명과 CSC명은 있어야 하고 CSCI명은 비워 둘 수 있다."""
    out = {}
    for key, name in KEYS.items():
        text = " ".join(str(values.get(key) or "").split())
        if len(text) > MAX_LEN:
            raise SettingsError(f"{name}이 너무 깁니다({MAX_LEN}자까지).")
        out[key] = text
    for key in ("project", "csc"):
        if not out[key]:
            raise SettingsError(f"{KEYS[key]}을 적으십시오.")
    return out


def save(directory: Path, values: Dict[str, str]) -> Path:
    """srtgen.json 에 쓴다. 파일에 다른 항목이 있으면 그대로 둔다. 읽을 수 없는 파일은 덮어쓰지 않는다."""
    path = directory / FILE_NAME
    data = _read(path) if path.exists() else {}
    for key, name in KEYS.items():
        data[name] = values.get(key, "")
    try:
        path.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))  # \n 그대로 (3.9 호환)
    except OSError as e:
        raise SettingsError(f"보고서 정보를 저장할 수 없습니다 ({e.strerror}): {path}")
    return path


def resolve(directory: Optional[Path], overrides: Dict[str, Optional[str]]) -> Tuple[Dict[str, str], str]:
    """명령줄 옵션 > srtgen.json > 기본값. (값, 경고). 파일을 읽을 수 없으면 경고를 내고 기본값을 쓴다."""
    values = dict(DEFAULTS)
    warning = ""
    try:
        values.update(load(directory)[0])
    except SettingsError as e:
        warning = str(e)
    values.update({k: v for k, v in overrides.items() if v is not None})
    return values, warning


_EXAMPLE = re.compile(r"O{3,}|○{2,}|◯{2,}|〇{2,}")    # 양식 예시의 자리 표시(OOO체계개발사업, ○○장치)


def placeholders(values: Dict[str, str]) -> List[str]:
    """아직 예시 값(OOO 등)이 남은 항목의 이름. 보고서는 만들되 알린다(지어 넣지 않고 사용자가 고치게 한다)."""
    return [name for key, name in KEYS.items() if _EXAMPLE.search(values.get(key, "") or "")]


def out_dir(directory: Optional[Path]) -> Path:
    """보고서를 만들 폴더: srtgen.json 의 "출력 폴더"(그 폴더 기준 상대 경로 또는 절대 경로), 없으면 srt_report.
    프로젝트 폴더 안에 두어 소스와 함께 형상관리한다. 연 것이 없으면 지금 폴더의 srt_report."""
    base = directory or Path.cwd()
    configured = ""
    path = base / FILE_NAME
    if path.is_file():
        try:
            value = _read(path).get(OUT_KEY)
            configured = value.strip() if isinstance(value, str) else ""
        except SettingsError:
            pass
    return base / (configured or DEFAULT_OUT)
