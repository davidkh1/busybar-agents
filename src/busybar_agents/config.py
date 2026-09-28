"""Configuration, read once from environment variables.

Every knob is an environment variable so the same settings work from a shell,
from a Claude Code hook, from a Codex hook, or from an MCP server.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

# The application_name every drawing and sound is filed under on the bar.
# Clearing this name removes everything we drew and nothing anyone else did.
APP_NAME = "busybar-agents"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


def _flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in _TRUE


def _int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        return default


def default_state_path() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "busybar-agents" / "hands.json"


@dataclass(frozen=True)
class Config:
    """Runtime settings. See README for the matching environment variables."""

    addr: str = "10.0.4.20"  # BUSYBAR_ADDR: USB address, or the bar's Wi-Fi address
    token: str | None = None  # BUSYBAR_TOKEN: access key, only needed over Wi-Fi
    priority: int = 50  # BUSYBAR_PRIORITY: 90+ shows over a running BUSY session
    sound: str | None = None  # BUSYBAR_SOUND: stock sound name, empty/off for silence
    ttl: int = 1800  # BUSYBAR_TTL: seconds a raised hand survives without a lower
    done_seconds: int = 8  # BUSYBAR_DONE_SECONDS: how long the done message stays
    ask_timeout: int = 20  # BUSYBAR_ASK_TIMEOUT: seconds to wait for a button
    dry_run: bool = False  # BUSYBAR_DRY_RUN: print payloads instead of drawing
    state_path: Path = default_state_path()  # BUSYBAR_STATE: shared hands file

    @classmethod
    def from_env(cls) -> Config:
        sound_raw = os.environ.get("BUSYBAR_SOUND", "").strip().lower()
        if sound_raw in _FALSE:
            sound = None
        elif sound_raw in _TRUE:
            sound = "reminder"
        else:
            sound = sound_raw
        state = os.environ.get("BUSYBAR_STATE")
        return cls(
            addr=os.environ.get("BUSYBAR_ADDR", cls.addr),
            token=os.environ.get("BUSYBAR_TOKEN") or None,
            priority=max(1, min(100, _int("BUSYBAR_PRIORITY", cls.priority))),
            sound=sound,
            ttl=max(1, _int("BUSYBAR_TTL", cls.ttl)),
            done_seconds=max(1, _int("BUSYBAR_DONE_SECONDS", cls.done_seconds)),
            ask_timeout=max(1, _int("BUSYBAR_ASK_TIMEOUT", cls.ask_timeout)),
            dry_run=_flag("BUSYBAR_DRY_RUN"),
            state_path=Path(state) if state else default_state_path(),
        )
