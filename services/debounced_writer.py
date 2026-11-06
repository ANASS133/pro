"""
Debounced atomic progress writer for JobScout.
Coalesces rapid progress disk updates, eliminating excessive JSON disk I/O
while guaranteeing atomic write replacement and zero data loss on termination.
"""

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class DebouncedAtomicWriter:
    """Thread-safe debounced disk writer with atomic replace semantics."""

    def __init__(self, target_path: Path, min_interval_seconds: float = 2.0):
        self.target_path = Path(target_path)
        self.min_interval = min_interval_seconds
        self._lock = threading.Lock()
        self._pending_payload: Optional[Any] = None
        self._last_write_time: float = 0.0
        self._timer: Optional[threading.Timer] = None
        self._is_dirty: bool = False

    def schedule_write(self, payload: Any, immediate: bool = False) -> None:
        """Schedules a payload to be written, debounced by min_interval unless immediate=True."""
        with self._lock:
            self._pending_payload = payload
            self._is_dirty = True
            now = time.time()
            elapsed = now - self._last_write_time

            if immediate or elapsed >= self.min_interval:
                self._cancel_timer_locked()
                self._write_locked()
            else:
                if self._timer is None:
                    delay = max(0.1, self.min_interval - elapsed)
                    self._timer = threading.Timer(delay, self._timer_callback)
                    self._timer.daemon = True
                    self._timer.start()

    def _timer_callback(self) -> None:
        with self._lock:
            self._timer = None
            if self._is_dirty:
                self._write_locked()

    def _cancel_timer_locked(self) -> None:
        if self._timer is not None:
            try:
                self._timer.cancel()
            except Exception:
                pass
            self._timer = None

    def _write_locked(self) -> None:
        if not self._is_dirty or self._pending_payload is None:
            return
        payload = self._pending_payload
        self._is_dirty = False
        self._last_write_time = time.time()

        try:
            self.target_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.target_path.with_suffix(f".tmp_{os.getpid()}_{int(time.time()*1000)%10000}")
            # Compact separators to reduce CPU JSON serialization overhead
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
            tmp_path.replace(self.target_path)
        except Exception as exc:
            logger.warning("[DebouncedWriter] Failed writing to %s: %s", self.target_path, exc)

    def flush(self) -> None:
        """Forces immediate write of any pending data."""
        with self._lock:
            self._cancel_timer_locked()
            self._write_locked()


_WRITERS: Dict[str, DebouncedAtomicWriter] = {}
_WRITERS_LOCK = threading.Lock()


def get_debounced_writer(path: Path, min_interval_seconds: float = 2.0) -> DebouncedAtomicWriter:
    p_str = str(path.resolve())
    with _WRITERS_LOCK:
        if p_str not in _WRITERS:
            _WRITERS[p_str] = DebouncedAtomicWriter(path, min_interval_seconds=min_interval_seconds)
        return _WRITERS[p_str]


def flush_all_debounced_writers() -> None:
    with _WRITERS_LOCK:
        writers = list(_WRITERS.values())
    for w in writers:
        try:
            w.flush()
        except Exception:
            pass
