"""진행 상황: 소스를 많이 읽을 때 화면(진행 막대)과 콘솔(진행 줄)에 보인다.

수집기(scanner.scan_entries)가 파일마다 부르는 progress(읽은 수, 전체 수, 지금 파일)를 받아,
화면 서버는 Progress 에 적어 두고(GET /api/progress 로 화면이 묻는다), 명령줄은 ConsoleProgress 로 한 줄에 고쳐 쓴다.
"""
from __future__ import annotations

import sys
import threading
import time
from typing import Callable, List, Optional, TextIO

Listener = Callable[[int, int, str], None]


class Progress:
    """화면 서버의 지금 작업. 요청을 처리하는 스레드가 쓰고, 진행을 묻는 다른 스레드가 읽는다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = {"busy": False, "phase": "", "done": 0, "total": 0, "file": "", "started": 0.0}
        self.listeners: List[Listener] = []         # 함께 알릴 곳(서버를 띄울 때의 콘솔 줄)

    @property
    def busy(self) -> bool:
        return bool(self._state["busy"])

    def start(self, phase: str) -> None:
        with self._lock:
            self._state.update(busy=True, phase=phase, done=0, total=0, file="", started=time.monotonic())

    def phase(self, phase: str) -> None:
        with self._lock:
            self._state.update(phase=phase, done=0, total=0, file="")

    def update(self, done: int, total: int, file: str) -> None:
        with self._lock:
            self._state.update(done=done, total=total, file=file)
        for listener in self.listeners:
            listener(done, total, file)

    def finish(self) -> None:
        with self._lock:
            self._state.update(busy=False, phase="", done=0, total=0, file="")

    def snapshot(self) -> dict:
        with self._lock:
            s = dict(self._state)
        started = s.pop("started")
        s["elapsed"] = round(time.monotonic() - started, 1) if s["busy"] else 0.0
        return s


class ConsoleProgress:
    """콘솔 한 줄에 '소스 읽는 중 120/3500 (3%) 파일' 을 고쳐 쓴다.
    콘솔이 아니면(파일로 돌린 출력) 쓰지 않고, 빨리 끝나는 작업은 보이지 않도록 delay 초 뒤부터 쓴다."""

    def __init__(self, label: str = "소스 읽는 중", stream: Optional[TextIO] = None, delay: float = 0.5,
                 every: float = 0.1) -> None:
        self.label, self.delay, self.every = label, delay, every
        self.stream = stream or sys.stderr
        self.enabled = bool(getattr(self.stream, "isatty", lambda: False)())
        self.started = time.monotonic()
        self.last = 0.0
        self.shown = False
        self.ever = False           # 한 번이라도 보였는가 (오래 걸린 작업이었는가)

    def note(self, text: str) -> None:
        """진행 수를 셀 수 없는 단계(보고서 쓰기 등)를 한 줄로 알린다. close 가 지운다."""
        if not self.enabled:
            return
        self.stream.write("\r" + text[:110].ljust(110))
        self.stream.flush()
        self.shown = self.ever = True

    def __call__(self, done: int, total: int, file: str) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        if done >= total:
            self.close()
            return
        if now - self.started < self.delay or now - self.last < self.every:
            return
        self.last = now
        pct = done * 100 // total if total else 0
        line = f"{self.label} {done}/{total} ({pct}%) {file}"
        self.stream.write("\r" + line[:110].ljust(110))
        self.stream.flush()
        self.shown = self.ever = True

    def close(self) -> None:
        if self.shown:
            self.stream.write("\r" + " " * 110 + "\r")
            self.stream.flush()
            self.shown = False
