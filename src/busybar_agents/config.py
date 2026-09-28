"""Settings, read once from environment variables."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

USB_ADDRESS = "10.0.4.20"  # fixed by the bar's firmware
APP_NAME = "busybar-agents"  # owner of everything we draw or play on the bar

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


def _flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in _TRUE


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, ""))
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
    """Runtime settings. Each field maps to a BUSYBAR_* variable, see README."""

    addr: str = USB_ADDRESS  # BUSYBAR_ADDR
    token: str | None = None  # BUSYBAR_TOKEN, Wi-Fi only
    priority: int = 50  # BUSYBAR_PRIORITY; 91+ overrides a focus session
    sound: str | None = None  # BUSYBAR_SOUND, a stock sound name
    ttl: int = 1800  # BUSYBAR_TTL, seconds a hand may stay up
    done_seconds: int = 8  # BUSYBAR_DONE_SECONDS
    hello_seconds: int = 4  # BUSYBAR_HELLO_SECONDS; 0 disables
    ask_timeout: int = 20  # BUSYBAR_ASK_TIMEOUT
    go_seconds: int = 8  # BUSYBAR_GO_SECONDS
    dry_run: bool = False  # BUSYBAR_DRY_RUN
    state_path: Path = default_state_path()  # BUSYBAR_STATE

    @property
    def wheel_path(self) -> Path:
        """The wheel switch file, beside the hands file."""
        return self.state_path.with_name("wheel.json")

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
            hello_seconds=max(0, _int("BUSYBAR_HELLO_SECONDS", cls.hello_seconds)),
            ask_timeout=max(1, _int("BUSYBAR_ASK_TIMEOUT", cls.ask_timeout)),
            go_seconds=max(1, _int("BUSYBAR_GO_SECONDS", cls.go_seconds)),
            dry_run=_flag("BUSYBAR_DRY_RUN"),
            state_path=Path(state) if state else default_state_path(),
        )
