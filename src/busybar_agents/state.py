"""Raised hands, shared between agents through one small JSON file."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - no locking outside POSIX
    fcntl = None  # type: ignore[assignment]


@dataclass
class Hand:
    agent: str  # claude, codex, ...
    session: str  # short session id
    project: str  # session name or folder, shown on the bar
    reason: str  # permission?, your turn, ...
    since: float  # unix time
    color: str | None = None  # session colour, a name or #RRGGBB; None means the agent's default

    @property
    def key(self) -> str:
        return f"{self.agent}:{self.session}"

    @property
    def age(self) -> float:
        return max(0.0, time.time() - self.since)


class HandsFile:
    """Reads and writes the hands file under an advisory lock."""

    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path.with_suffix(".lock"), "w") as lock:
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
                continue  # row from an older version
        return hands

    def _write(self, hands: list[Hand]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"hands": [asdict(h) for h in hands]}, indent=2))
        os.replace(tmp, self.path)

    def load(self) -> list[Hand]:
        with self._locked():
            return self._read()

    def raise_hand(self, hand: Hand) -> list[Hand]:
        """Add or replace a hand. Returns all hands, oldest first."""
        with self._locked():
            hands = [h for h in self._read() if h.key != hand.key]
            hands.append(hand)
            hands.sort(key=lambda h: h.since)
            self._write(hands)
            return hands

    def take(self, agent: str, session: str) -> tuple[bool, list[Hand]]:
        """Remove a hand. Returns (was it up, hands still up)."""
        key = f"{agent}:{session}"
        with self._locked():
            hands = self._read()
            remaining = [h for h in hands if h.key != key]
            removed = len(remaining) != len(hands)
            if removed:
                self._write(remaining)
            return removed, remaining

    def lower(self, agent: str, session: str) -> list[Hand]:
        """Remove a hand. Returns the hands still up."""
        return self.take(agent, session)[1]

    def prune(self, ttl: int) -> list[Hand]:
        """Drop hands older than ttl seconds."""
        cutoff = time.time() - ttl
        with self._locked():
            hands = [h for h in self._read() if h.since >= cutoff]
            self._write(hands)
            return hands

    def clear(self) -> None:
        with self._locked():
            self._write([])


class WheelFile:
    """The wheel switch set from inside a session; hooks read it under the BUSYBAR_ASK/GO variables."""

    def __init__(self, path: Path):
        self.path = path

    def read(self) -> dict[str, bool]:
        try:
            raw = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {"ask": False, "go": False}
        return {key: bool(raw.get(key)) for key in ("ask", "go")}

    def write(self, on: bool) -> dict[str, bool]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        state = {"ask": on, "go": on}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        os.replace(tmp, self.path)
        return state
