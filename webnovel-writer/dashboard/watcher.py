"""
Watchdog 文件变更监听器 + SSE 推送

递归监控 PROJECT_ROOT/.webnovel/ 下的 workflow / observability / review 工件，
通过 SSE 通知前端刷新数据。
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import AsyncGenerator

from watchdog.events import FileCreatedEvent, FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

WATCH_ROOT_NAMES = {"state.json", "index.db", "workflow_state.json"}
WATCH_SUBDIRS = {"write_workflow", "observability", "reviews", "summaries"}
WATCH_SUFFIXES = {".json", ".jsonl", ".log", ".md", ".db"}


def _should_watch_path(path: Path) -> bool:
    if not path.name:
        return False
    if path.name in WATCH_ROOT_NAMES:
        return True
    if path.suffix not in WATCH_SUFFIXES:
        return False
    return any(part in WATCH_SUBDIRS for part in path.parts)


def _path_category(path: Path) -> str:
    parts = set(path.parts)
    if "write_workflow" in parts:
        return "write_workflow"
    if "observability" in parts:
        return "observability"
    if "reviews" in parts:
        return "reviews"
    if "summaries" in parts:
        return "summaries"
    if path.name == "workflow_state.json":
        return "workflow_state"
    if path.name == "state.json":
        return "state"
    if path.name == "index.db":
        return "index"
    return "misc"


class _WebnovelFileHandler(FileSystemEventHandler):
    """关注 .webnovel/ 目录下关键文件的修改/创建事件。"""

    def __init__(self, notify_callback, watch_root: Path):
        super().__init__()
        self._notify = notify_callback
        self._watch_root = watch_root.resolve()

    def _handle(self, src_path: str, kind: str):
        path = Path(src_path)
        try:
            rel = path.resolve().relative_to(self._watch_root)
        except Exception:
            return
        if _should_watch_path(rel):
            self._notify(path, rel, kind)

    def on_modified(self, event: FileModifiedEvent):
        if event.is_directory:
            return
        self._handle(event.src_path, "modified")

    def on_created(self, event: FileCreatedEvent):
        if event.is_directory:
            return
        self._handle(event.src_path, "created")


class FileWatcher:
    """管理 watchdog Observer 和 SSE 客户端订阅。"""

    def __init__(self):
        self._observer: Observer | None = None
        self._subscribers: list[asyncio.Queue] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._watch_dir: Path | None = None

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=128)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def _on_change(self, path: Path, rel_path: Path, kind: str):
        msg = json.dumps(
            {
                "file": path.name,
                "relative_path": str(rel_path).replace("\\", "/"),
                "category": _path_category(rel_path),
                "kind": kind,
                "ts": time.time(),
            },
            ensure_ascii=False,
        )
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._dispatch, msg)

    def _dispatch(self, msg: str):
        dead: list[asyncio.Queue] = []
        for q in self._subscribers:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                dead.append(q)
        for dq in dead:
            self.unsubscribe(dq)

    def start(self, watch_dir: Path, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._watch_dir = watch_dir.resolve()
        handler = _WebnovelFileHandler(self._on_change, self._watch_dir)
        self._observer = Observer()
        self._observer.schedule(handler, str(self._watch_dir), recursive=True)
        self._observer.daemon = True
        self._observer.start()

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=3)
            self._observer = None
