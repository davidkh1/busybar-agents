"""The event log: one JSON line per hook event and per call to the bar.

Hook bridges, the command line and the panel all append to ``events.jsonl``
beside the hands file, so one file answers "who drew that, and what did the
bar say?". A hook line and the CLI line it caused share a six-character
``trace``. The bridges are standard-library scripts and carry their own copy
of ``record``; keep the shapes in step.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

LOG_NAME = "events.jsonl"
MAX_BYTES = 2_000_000  # past this the file becomes events.jsonl.1 and a new one starts
SHELLS = {"sh", "bash", "zsh", "fish", "dash"}


def log_path(state_path: Path) -> Path:
    """``events.jsonl`` beside the hands file."""
    return state_path.with_name(LOG_NAME)


def record(path: Path, **fields: Any) -> None:
    """Append one stamped event; fields holding None are left out. Never raises: logging must not break a hook."""
    entry = {"t": round(time.time(), 3), **{key: value for key, value in fields.items() if value is not None}}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > MAX_BYTES:
            os.replace(path, path.with_name(path.name + ".1"))
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, separators=(",", ":"), default=str) + "\n")
    except OSError:
        pass


def parse(line: str) -> dict[str, Any] | None:
    try:
        event = json.loads(line)
    except ValueError:
        return None
    return event if isinstance(event, dict) and "t" in event else None


def _tail(path: Path, limit: int) -> list[str]:
    """The last ``limit`` lines, read from the end of the file."""
    if limit <= 0:
        return []
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size, data = handle.tell(), b""
            while size > 0 and data.count(b"\n") <= limit:
                step = min(65536, size)
                size -= step
                handle.seek(size)
                data = handle.read(step) + data
    except OSError:
        return []
    return data.decode("utf-8", "replace").splitlines()[-limit:]


def read(path: Path, limit: int = 40) -> list[dict[str, Any]]:
    """The last ``limit`` events, oldest first, reaching into the rotated file when the current one is short."""
    lines = _tail(path, limit)
    if len(lines) < limit:
        lines = _tail(path.with_name(path.name + ".1"), limit - len(lines)) + lines
    return [event for event in map(parse, lines) if event]


@dataclass
class Cursor:
    """Hands out what was appended since the last poll. Starts at the current end."""

    path: Path
    position: int | None = None
    rest: bytes = field(default=b"", repr=False)  # a line still waiting for its newline

    def poll(self) -> list[dict[str, Any]]:
        try:
            size = self.path.stat().st_size
        except OSError:
            size = 0
        if self.position is None:
            self.position = size
            return []
        if size < self.position:  # rotated or truncated: the new file starts over
            self.position, self.rest = 0, b""
        if size == self.position:
            return []
        try:
            with open(self.path, "rb") as handle:
                handle.seek(self.position)
                data = self.rest + handle.read(size - self.position)
        except OSError:
            return []
        self.position = size
        *lines, self.rest = data.split(b"\n")
        return [event for event in (parse(line.decode("utf-8", "replace")) for line in lines if line.strip()) if event]


def follow(path: Path, poll_seconds: float = 0.25) -> Iterator[dict[str, Any]]:
    """Events as they are appended, forever."""
    cursor = Cursor(path)
    while True:
        yield from cursor.poll()
        time.sleep(poll_seconds)


def agent_process(parents: Any) -> str:
    """The nearest ancestor that is not a shell or Python: the agent that fired the hook."""
    for command in parents or []:
        name = os.path.basename(str(command).split(" ", 1)[0])
        if name and name not in SHELLS and not name.startswith("python"):
            return str(command)
    return ""


def format_event(event: dict[str, Any]) -> str:
    """One readable line: time, source, agent and session, what happened, outcome, trace."""
    stamp = time.strftime("%H:%M:%S", time.localtime(float(event.get("t", 0))))
    src = str(event.get("src", "?"))
    who = " ".join(str(event[key]) for key in ("agent", "session") if event.get(key))
    parts: list[str] = []
    if src == "hook":
        parts.append(" ".join(str(event[key]) for key in ("event", "source", "kind", "tool") if event.get(key)))
        if event.get("verb"):
            parts.append(f"-> {event['verb']}")
        if event.get("skip"):
            parts.append(f"skipped: {event['skip']}")
        if event.get("decision"):
            parts.append(f"decision: {event['decision']}")
        if event.get("detail"):
            parts.append(str(event["detail"]))
        if event.get("project"):
            parts.append(str(event["project"]))
        process = agent_process(event.get("parents"))
        if process:
            parts.append(f"from {process}")
    else:
        parts.append(str(event.get("verb", "?")))
        if event.get("key"):
            parts.append(str(event["key"]))
        if event.get("shown"):
            parts.append(" | ".join(map(str, event["shown"])))
        elif event.get("project"):
            parts.append(str(event["project"]))
        if event.get("bar"):
            parts.append(", ".join(map(str, event["bar"])))
    if event.get("result") is not None:
        parts.append(f"= {event['result']}")
    if event.get("ms") is not None:
        parts.append(f"{event['ms']} ms")
    if event.get("error"):
        parts.append(f"ERROR {event['error']}")
    trace = f"[{event['trace']}]" if event.get("trace") else ""
    return "  ".join(piece for piece in (stamp, f"{src:5}", f"{who:17}", "  ".join(p for p in parts if p), trace) if piece.strip()).rstrip()
