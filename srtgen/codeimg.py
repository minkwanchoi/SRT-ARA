"""발췌한 코드를 줄 번호가 붙은 그림(PNG)으로 만든다 (코드 캡처 대용).

Pillow 가 필요하다. Pygments 가 있으면 구문 강조를 한다.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Tuple

SCALE = 2                 # 인쇄 선명도를 위해 2배 크기로 그린다
FONT_SIZE = 13 * SCALE
PAD = 10 * SCALE
LINE_GAP = 5 * SCALE
BG = "#FFFFFF"
GUTTER_BG = "#F0F0F0"
GUTTER_FG = "#808080"
BORDER = "#B0B0B0"
DEFAULT_FG = "#000000"

_FONT_CANDIDATES = [
    ("D2Coding.ttf", 0), ("D2Coding.ttc", 0), ("gulim.ttc", 1), ("NanumGothicCoding.ttf", 0),
    ("malgun.ttf", 0), ("consola.ttf", 0),
]
_LEXERS = {"C": "c", "C++": "cpp", "Java": "java", "C#": "csharp"}


def available() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def _font():
    from PIL import ImageFont
    override = os.environ.get("SRTGEN_FONT")
    candidates = ([(override, 0)] if override else []) + _FONT_CANDIDATES
    for name, index in candidates:
        try:
            return ImageFont.truetype(name, FONT_SIZE, index=index)
        except OSError:
            continue
    return ImageFont.load_default()


def _colored(code: str, language: str) -> Optional[List[List[Tuple[str, str]]]]:
    """줄마다 (색, 글자) 목록. Pygments 가 없으면 None."""
    try:
        from pygments import lex
        from pygments.lexers import get_lexer_by_name
        from pygments.token import Comment, Keyword, Number, String
    except ImportError:
        return None
    palette = [(Comment, "#008000"), (Keyword, "#0000C0"), (String, "#A31515"), (Number, "#098658")]
    try:
        lexer = get_lexer_by_name(_LEXERS.get(language, "text"), stripnl=False, ensurenl=False)
    except Exception:
        return None
    rows: List[List[Tuple[str, str]]] = [[]]
    for ttype, text in lex(code, lexer):
        color = next((c for t, c in palette if ttype in t), DEFAULT_FG)
        parts = text.split("\n")
        for i, part in enumerate(parts):
            if i:
                rows.append([])
            if part:
                rows[-1].append((color, part))
    return rows


def render(lines: List[Tuple[int, str]], language: str, out_dir: Path, stem: str,
           max_lines: int = 30) -> List[Path]:
    """코드를 max_lines 줄씩 나누어 그림으로 저장하고 경로 목록을 돌려준다."""
    from PIL import Image, ImageDraw

    out_dir.mkdir(parents=True, exist_ok=True)
    font = _font()
    colored = _colored("\n".join(t for _, t in lines), language)
    if colored is None or len(colored) != len(lines):
        colored = [[(DEFAULT_FG, t)] if t else [] for _, t in lines]

    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    ascent, descent = font.getmetrics() if hasattr(font, "getmetrics") else (FONT_SIZE, 0)
    line_h = ascent + descent + LINE_GAP
    digits = max(3, len(str(lines[-1][0]))) if lines else 3
    gutter_w = int(probe.textlength("0" * digits, font=font)) + PAD * 2

    paths: List[Path] = []
    chunks = [range(i, min(i + max_lines, len(lines))) for i in range(0, max(len(lines), 1), max_lines)]
    for n, chunk in enumerate(chunks):
        width = gutter_w + PAD * 2 + max(
            [int(probe.textlength(lines[i][1], font=font)) for i in chunk] + [200 * SCALE])
        height = PAD * 2 + line_h * max(len(chunk), 1) - LINE_GAP
        img = Image.new("RGB", (width, height), BG)
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, gutter_w, height), fill=GUTTER_BG)
        y = PAD
        for i in chunk:
            number = str(lines[i][0])
            draw.text((gutter_w - PAD - probe.textlength(number, font=font), y), number,
                      font=font, fill=GUTTER_FG)
            x = gutter_w + PAD
            for color, text in colored[i]:
                draw.text((x, y), text, font=font, fill=color)
                x += probe.textlength(text, font=font)
            y += line_h
        draw.rectangle((0, 0, width - 1, height - 1), outline=BORDER, width=SCALE)
        suffix = f"_{n + 1}" if len(chunks) > 1 else ""
        path = out_dir / f"{stem}{suffix}.png"
        img.save(path, dpi=(96 * SCALE, 96 * SCALE))
        paths.append(path)
    return paths
