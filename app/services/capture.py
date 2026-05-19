"""Watch the Olympus auto-save folder for new TIFFs and hand them to a callback.

The watcher must be robust to:
- A new daily folder (D:\\Auto save\\folder_YYYYMMDD) appearing at midnight → watch the
  ROOT recursively, not a specific daily folder.
- Olympus writing the file in chunks → wait for the file size to be stable across
  two consecutive polls before emitting.
- The same file triggering multiple events → de-dupe by path.
"""

from __future__ import annotations

import fnmatch
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileCreatedEvent, FileSystemEventHandler
from watchdog.observers import Observer

log = logging.getLogger(__name__)

OnNewFile = Callable[[Path], None]


class _Handler(FileSystemEventHandler):
    def __init__(
        self,
        patterns: list[str],
        on_candidate: Callable[[Path], None],
    ) -> None:
        self._patterns = patterns
        self._on_candidate = on_candidate

    def _matches(self, name: str) -> bool:
        return any(fnmatch.fnmatch(name.lower(), p.lower()) for p in self._patterns)

    def on_created(self, event: FileCreatedEvent) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        path = Path(event.src_path)
        if self._matches(path.name):
            self._on_candidate(path)

    def on_moved(self, event) -> None:  # type: ignore[override]
        # Some apps write a temp file and rename to the final name.
        if event.is_directory:
            return
        path = Path(event.dest_path)
        if self._matches(path.name):
            self._on_candidate(path)


class FileWatcher:
    """Watch a root folder (recursive) and call `on_ready` with each stable new file.

    Stability check: poll `st_size` every `stable_poll_ms` ms and emit once the size
    has been unchanged for `stable_required_checks` consecutive polls AND the file
    can be opened for reading without ShareViolation.
    """

    def __init__(
        self,
        root: Path,
        patterns: list[str],
        *,
        on_ready: OnNewFile,
        recursive: bool = True,
        stable_poll_ms: int = 200,
        stable_required_checks: int = 2,
    ) -> None:
        self.root = Path(root)
        self.patterns = patterns
        self._on_ready = on_ready
        self._recursive = recursive
        self._poll = stable_poll_ms / 1000.0
        self._required = max(1, stable_required_checks)

        self._observer: Observer | None = None
        self._seen: set[Path] = set()
        self._seen_lock = threading.Lock()
        self._pending: list[Path] = []
        self._pending_lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._observer is not None:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        handler = _Handler(self.patterns, self._enqueue)
        obs = Observer()
        obs.schedule(handler, str(self.root), recursive=self._recursive)
        obs.start()
        self._observer = obs

        self._stop.clear()
        self._worker = threading.Thread(target=self._drain, daemon=True)
        self._worker.start()
        log.info("FileWatcher started on %s (recursive=%s)", self.root, self._recursive)

    def stop(self) -> None:
        self._stop.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=3)
            self._observer = None
        if self._worker is not None:
            self._worker.join(timeout=3)
            self._worker = None
        with self._seen_lock:
            self._seen.clear()
        with self._pending_lock:
            self._pending.clear()
        log.info("FileWatcher stopped")

    def _enqueue(self, path: Path) -> None:
        with self._seen_lock:
            if path in self._seen:
                return
            self._seen.add(path)
        with self._pending_lock:
            self._pending.append(path)

    def _drain(self) -> None:
        """Background worker that waits until each queued file is fully written."""
        while not self._stop.is_set():
            time.sleep(self._poll)
            with self._pending_lock:
                batch = list(self._pending)
                self._pending.clear()

            still_pending: list[Path] = []
            for path in batch:
                try:
                    if self._is_stable(path):
                        self._emit(path)
                    else:
                        still_pending.append(path)
                except FileNotFoundError:
                    pass  # deleted before we could read
                except Exception:
                    log.exception("Error checking %s", path)

            if still_pending:
                with self._pending_lock:
                    self._pending.extend(still_pending)

    def _is_stable(self, path: Path) -> bool:
        if not path.exists():
            return False
        last = path.stat().st_size
        for _ in range(self._required):
            time.sleep(self._poll)
            if not path.exists():
                return False
            cur = path.stat().st_size
            if cur != last:
                return False
            last = cur
        # Final check: can we open it without a share-violation (Olympus released it)?
        try:
            with path.open("rb") as f:
                f.read(16)
        except OSError:
            return False
        return True

    def _emit(self, path: Path) -> None:
        try:
            self._on_ready(path)
        except Exception:
            log.exception("on_ready callback failed for %s", path)
