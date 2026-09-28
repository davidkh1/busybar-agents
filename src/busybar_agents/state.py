"""The shared list of raised hands.

Several agents from several vendors can be running at once, and they all draw
on one 72x16 strip. So nobody draws directly: each adapter records its hand
here, and the bar is redrawn from the whole list. The file lives outside any
repository, is tiny, and is protected by an advisory lock where the platform
has one.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

try:  # POSIX only; on other platforms we fall back to no locking.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


@dataclass
class Hand:
    agent: str  # "claude", "codex", "gemini", ...
    session: str  # short session id, so two Claude sessions are two hands
    project: str  # usually the working directory's name
    reason: str  # "needs permission", "waiting for you", ...
    since: float  # unix time the hand went up

    @property
    def key(self) -> str:
        return f"{self.agent}:{self.session}"

    @property
    def age(self) -> float:
        return max(0.0, time.time() - self.since)


class HandsFile:
    """Load, change and save the list of hands atomically."""

    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(".lock")
        with open(lock_path, "w") as lock:
            if fcntl is not None:
                fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock, fcntl.LOCK_UN)

    def _read(self) -> list[Hand]:
        try:
            raw = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        hands = []
        for item in raw.get("hands", []):
            try:
                hands.append(Hand(**item))
            except TypeError:
                continue  # a row from an older version; drop it
        return hands

    def _write(self, hands: list[Hand]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"hands": [asdict(h) for h in hands]}, indent=2))
        os.replace(tmp, self.path)

    def load(self) -> list[Hand]:
        with self._locked():
            return self._read()

    def raise_hand(self, hand: Hand) -> list[Hand]:
        """Add or replace one hand. Returns the full list, oldest first."""
        with self._locked():
            hands = [h for h in self._read() if h.key != hand.key]
            hands.append(hand)
            hands.sort(key=lambda h: h.since)
            self._write(hands)
            return hands

    def lower(self, agent: str, session: str) -> list[Hand]:
        """Remove one hand. Returns what is still up."""
        key = f"{agent}:{session}"
        with self._locked():
            hands = [h for h in self._read() if h.key != key]
            self._write(hands)
            return hands

    def prune(self, ttl: int) -> list[Hand]:
        """Drop hands older than ttl seconds: their session probably died."""
        cutoff = time.time() - ttl
        with self._locked():
            hands = [h for h in self._read() if h.since >= cutoff]
            self._write(hands)
            return hands

    def clear(self) -> None:
        with self._locked():
            self._write([])
