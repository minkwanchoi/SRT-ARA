"""그림 파일의 픽셀 크기를 표준 라이브러리만으로 읽는다 (PNG, JPEG, GIF, BMP)."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Optional, Tuple

MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".gif": "image/gif", ".bmp": "image/bmp"}


def _png_chunks(data: bytes):
    pos = 8
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        yield kind, pos, data[pos + 8:pos + 8 + length]
        pos += 12 + length


def scale(path: Path) -> float:
    """화면 기준(96dpi)으로 그릴 때의 배율. 해상도 정보가 있는 PNG 만 줄이고, 나머지는 1 이다.

    화면에서 만든 다이어그램은 선명하게 보이도록 2배 크기(192dpi)로 저장하므로 0.5 가 된다.
    """
    data = path.read_bytes()[:4096]
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return 1.0
    for kind, _pos, body in _png_chunks(data):
        if kind == b"pHYs" and len(body) == 9 and body[8] == 1:
            dpi = struct.unpack(">I", body[:4])[0] * 0.0254
            return 96 / dpi if dpi > 97 else 1.0
        if kind == b"IDAT":
            break
    return 1.0


def with_dpi(data: bytes, dpi: int) -> bytes:
    """PNG 에 해상도 정보(pHYs)를 넣는다. 이미 있거나 PNG 가 아니면 그대로 돌려준다."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return data
    for kind, pos, body in _png_chunks(data):
        if kind == b"pHYs":
            return data
        if kind == b"IHDR":
            after = pos + 12 + len(body)
            chunk = b"pHYs" + struct.pack(">IIB", round(dpi / 0.0254), round(dpi / 0.0254), 1)
            return data[:after] + struct.pack(">I", 9) + chunk + struct.pack(">I", zlib.crc32(chunk)) + data[after:]
    return data


def media_type(path: Path) -> Optional[str]:
    return MEDIA_TYPES.get(path.suffix.lower())


def size(path: Path) -> Optional[Tuple[int, int]]:
    data = path.read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", data[6:10])
    if data[:2] == b"BM" and len(data) >= 26:
        w, h = struct.unpack("<ii", data[18:26])
        return w, abs(h)
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    return None
