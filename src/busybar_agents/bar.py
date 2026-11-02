"""Drawing on the bar and reading its wheel.

Payload builders are pure functions returning the draw API's JSON. ``Bar``
is the only thing that talks to the device, through busylib.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import re
import sys
from typing import Any, Sequence

from busylib import AsyncBusyBar
from busylib.features import assets, notification

from .config import APP_NAME, Config
from .state import Hand
from .text import sanitize

# Anthropic palette, #RRGGBBAA.
CLAUDE_ORANGE = "#D97757FF"
IVORY = "#F0EEE6FF"
AGENT_COLORS = {"claude": CLAUDE_ORANGE, "codex": "#FFFFFFFF", "gemini": "#4C8DF6FF"}
DEFAULT_COLOR = "#FFB000FF"
# Claude Code's /color names, as the bar's LEDs show them.
SESSION_COLORS = {
    "red": "#FF3B30FF",
    "orange": CLAUDE_ORANGE,
    "yellow": "#FFCC00FF",
    "green": "#34C759FF",
    "cyan": "#32ADE6FF",
    "blue": "#4C8DF6FF",
    "purple": "#AF52DEFF",
    "pink": "#FF2D9BFF",
    "magenta": "#FF00FFFF",
    "white": "#FFFFFFFF",
}

# Front strip: 72x16, a 16 px icon at the left, text after it.
FRONT_WIDTH = 72
ICON_WIDTH = 16
TEXT_X = ICON_WIDTH + 2
TEXT_WIDTH = FRONT_WIDTH - TEXT_X
SCROLL_THRESHOLD_CHARS = {"bold": 8, "tiny": 12}  # longer lines scroll
SCROLL_RATE = 1200  # pixels per minute
SCROLL_START_DELAY_MS = 1500
SCROLL_REPEAT_DELAY_MS = 1200

REQUEST_TIMEOUT = 5.0  # seconds
DWELL_SECONDS = 2.5  # resting on an option this long picks it

# Claude Code's mascot, 16x10; "w" is the white of the eyes.
MASCOT = {
    "ready": [
        "..oooooooooooo..",
        "..oooooooooooo..",
        "..oowoooooowoo..",
        "..oowoooooowoo..",
        "oooooooooooooooo",
        "oooooooooooooooo",
        "..oooooooooooo..",
        "..oooooooooooo..",
        "...o.o....o.o...",
        "...o.o....o.o...",
    ],
    "up": [  # arm raised
        "..oooooooooooo.o",
        "..oooooooooooo.o",
        "..oowoooooowoo.o",
        "..oowoooooowoo.o",
        "oooooooooooooooo",
        "oooooooooooooooo",
        "..oooooooooooo..",
        "..oooooooooooo..",
        "...o.o....o.o...",
        "...o.o....o.o...",
    ],
    "done": [  # eyes closed, happy
        "..oooooooooooo..",
        "..oooooooooooo..",
        "..oooooooooooo..",
        "..owwoooooowwo..",
        "oooooooooooooooo",
        "oooooooooooooooo",
        "..oooooooooooo..",
        "..oooooooooooo..",
        "...o.o....o.o...",
        "...o.o....o.o...",
    ],
}
# Other agents: a terminal prompt.
PROMPT_GLYPH = [
    "..oo............",
    "...oo...........",
    "....oo..........",
    ".....oo.........",
    "......oo........",
    ".....oo.........",
    "....oo..........",
    "...oo...........",
    "..oo............",
    "..........oooooo",
]


def resolve_color(agent: str, color: str | None = None) -> str:
    """The session's colour when it is a known name or hex, else the agent's default, as #RRGGBBAA."""
    if color:
        name = color.strip().lower()
        if name in SESSION_COLORS:
            return SESSION_COLORS[name]
        if re.fullmatch(r"#[0-9a-f]{6}", name):
            return name.upper() + "FF"
        if re.fullmatch(r"#[0-9a-f]{8}", name):
            return name.upper()
    return AGENT_COLORS.get(agent.lower(), DEFAULT_COLOR)


def xpm(rows: Sequence[str], colors: dict[str, str]) -> str:
    """Rows of characters plus a colour per character, as XPM2."""
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise ValueError("bitmap rows differ in width")
    header = ["! XPM2", f"{width} {len(rows)} {len(colors)} 1"]
    header += [f"{char} c {value}" for char, value in colors.items()]
    return "\n".join([*header, *rows])


def icon_element(agent: str, timeout: int, mood: str = "ready", color: str | None = None) -> dict[str, Any]:
    """Inline bitmap; one element type for id 10, which the firmware requires."""
    color = resolve_color(agent, color)[:7]
    if agent.lower() == "claude":
        data = xpm(MASCOT[mood], {".": "none", "o": color, "w": "#FFFFFF"})
    else:
        data = xpm(PROMPT_GLYPH, {".": "none", "o": color})
    return {"id": "10", "type": "xpmbitmap", "x": 0, "y": 8, "align": "mid_left", "display": "front", "timeout": timeout, "data": data}


def text_element(element_id: str, text: str, font: str, color: str, y: int, align: str, timeout: int, x: int = TEXT_X) -> dict[str, Any]:
    """A line of text; from ``x`` to the right edge. Lines too long for that room scroll."""
    element: dict[str, Any] = {
        "id": element_id,
        "type": "text",
        "x": x,
        "y": y,
        "align": align,
        "display": "front",
        "timeout": timeout,
        "text": text,
        "font": font,
        "color": color,
    }
    width = FRONT_WIDTH - x
    if len(text) > SCROLL_THRESHOLD_CHARS.get(font, 12) * width // TEXT_WIDTH:
        element.update(width=width, scroll_rate=SCROLL_RATE, scroll_start_delay=SCROLL_START_DELAY_MS, scroll_repeat_delay=SCROLL_REPEAT_DELAY_MS)
    return element


def notice(agent: str, line_1: str, line_2: str, timeout: int, cfg: Config, mood: str = "ready", color: str | None = None) -> dict[str, Any]:
    """Icon, bold headline in the session's colour (else the agent's), small detail line."""
    color = resolve_color(agent, color)
    elements = [
        icon_element(agent, timeout, mood, color),
        text_element("11", sanitize(line_1, 12) or "AGENT", "bold", color, -1, "top_left", timeout),
    ]
    detail = sanitize(line_2)
    if detail:
        elements.append(text_element("12", detail, "tiny", IVORY, 15, "bottom_left", timeout))
    return {"application_name": APP_NAME, "priority": cfg.priority, "led_notification_color": color, "elements": elements}


def hands_payload(hands: Sequence[Hand], cfg: Config) -> dict[str, Any]:
    """The strip while hands are up."""
    ordered = sorted(hands, key=lambda h: h.since)
    if len(ordered) == 1:
        hand = ordered[0]
        return notice(hand.agent, hand.agent.upper(), f"{hand.reason} - {hand.project}", cfg.ttl, cfg, mood="up", color=hand.color)
    agents = {h.agent.lower() for h in ordered}
    agent = ordered[0].agent if len(agents) == 1 else "agents"
    colors = {h.color for h in ordered}
    color = ordered[0].color if len(colors) == 1 else None  # mixed colours fall back to the agent's
    projects = ", ".join(dict.fromkeys(sanitize(h.project, 20) for h in ordered))
    return notice(agent, f"{len(ordered)} AGENTS", projects, cfg.ttl, cfg, mood="up", color=color)


def done_payload(hand: Hand, message: str, cfg: Config) -> dict[str, Any]:
    return notice(hand.agent, message, hand.project, cfg.done_seconds, cfg, mood="done", color=hand.color)


def hello_payload(agent: str, project: str, cfg: Config, color: str | None = None) -> dict[str, Any]:
    """READY over the session's name, so the blip says which session just started."""
    return notice(agent, "READY", project, max(1, cfg.hello_seconds), cfg, color=color)


def choice_payload(agent: str, title: str, options: Sequence[str], index: int, timeout: int, cfg: Config, color: str | None = None) -> dict[str, Any]:
    return notice(agent, options[index], f"{index + 1}/{len(options)} {title}", timeout, cfg, mood="up", color=color)


def ask_payload(agent: str, question: str, detail: str, timeout: int, cfg: Config, color: str | None = None) -> dict[str, Any]:
    return notice(agent, question, detail, timeout, cfg, mood="up", color=color)


def say_payload(agent: str, text: str, detail: str, seconds: int, cfg: Config, color: str | None = None, icon: bool = True) -> dict[str, Any]:
    """A free message: bold headline in the colour, small detail line; the agent's mascot unless ``icon`` is off."""
    if icon:
        return notice(agent, text, detail, seconds, cfg, color=color)
    color = resolve_color(agent, color)
    elements = [text_element("11", sanitize(text, 24) or "HELLO", "bold", color, -1 if detail else 0, "top_left" if detail else "mid_left", seconds, x=0)]
    if sanitize(detail):
        elements.append(text_element("12", sanitize(detail), "tiny", IVORY, 15, "bottom_left", seconds, x=0))
    return {"application_name": APP_NAME, "priority": cfg.priority, "led_notification_color": color, "elements": elements}


def texts(payload: dict[str, Any]) -> list[str]:
    """The visible words, in order."""
    return [e["text"] for e in payload["elements"] if e.get("text")]


class Gestures:
    """Wheel and Back button as a queue of forward, back and cancel."""

    def __init__(self, client: AsyncBusyBar):
        self.client = client
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.task: asyncio.Task | None = None

    async def __aenter__(self) -> "Gestures":
        self.task = asyncio.create_task(self._pump())
        return self

    async def __aexit__(self, *exc) -> None:
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass

    async def _pump(self) -> None:
        events = importlib.import_module("busylib.features.input_events")
        try:
            async for message in self.client.stream_status_ws():
                if not isinstance(message, dict):
                    continue
                for event in events.input_events(message):
                    if isinstance(event, events.EncoderEvent) and event.delta:
                        await self.queue.put("forward" if event.delta > 0 else "back")
                    elif isinstance(event, events.ButtonEvent) and event.is_press and event.button == "back":
                        await self.queue.put("cancel")
        except Exception as err:  # stream dropped; the caller times out
            print_error(f"input stream ended: {type(err).__name__}: {err}")

    async def next(self, timeout: float) -> str | None:
        try:
            return await asyncio.wait_for(self.queue.get(), timeout)
        except asyncio.TimeoutError:
            return None


# Read-only endpoints behind ``Bar.snapshot``: key, path, and the value to keep.
EXTRAS = (
    ("busy", "/api/busy/snapshot", lambda data: (data.get("snapshot") or {}).get("type")),
    ("brightness", "/api/display/brightness", lambda data: data.get("value")),
    ("volume", "/api/audio/volume", lambda data: data.get("volume")),
    ("transport", "/api/transport", lambda data: data.get("type")),
)


class Bar:
    """One connection to the bar; use as ``async with Bar(cfg) as bar``.

    ``trail`` keeps one short note per step taken on the device, for the event log.
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.client = AsyncBusyBar(cfg.addr, token=cfg.token)
        self.trail: list[dict[str, Any]] = []

    async def __aenter__(self) -> "Bar":
        await self.client.__aenter__()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.client.__aexit__(*exc)

    def _step(self, op: str, note: str, **extra: Any) -> None:
        self.trail.append({"op": op, "note": note, **extra})

    async def draw(self, payload: dict[str, Any]) -> None:
        shown = texts(payload)
        if self.cfg.dry_run:
            print(json.dumps(payload, indent=2))
            self._step("draw", "draw:dry-run", texts=shown, payload=payload)
            return
        try:
            await self.client.api_request("POST", "/api/display/draw", json_payload=payload, timeout=REQUEST_TIMEOUT)
        except Exception as err:
            if "409" not in str(err):
                self._step("draw", "draw:error", texts=shown, payload=payload)
                raise
            self._step("draw", "draw:busy", texts=shown, payload=payload)
            print_error("not drawn: a focus session is running (BUSYBAR_PRIORITY=91 overrides)")
            return
        self._step("draw", "draw:drawn", texts=shown, payload=payload)

    async def clear(self) -> None:
        if self.cfg.dry_run:
            print(json.dumps({"clear": APP_NAME}))
            self._step("clear", "clear:dry-run")
            return
        await self.client.display_clear(application_name=APP_NAME, timeout=REQUEST_TIMEOUT)
        self._step("clear", "clear")

    async def play(self, sound: str) -> None:
        """Play a stock sound by short name, e.g. reminder."""
        if self.cfg.dry_run:
            print(json.dumps({"play": sound}))
            self._step("play", f"play:{sound}:dry-run")
            return
        try:
            asset = await notification.resolve_sound(self.client, sound, application_name=APP_NAME)
        except ValueError:
            # busylib lists other applications' uploads as app/name but resolves only our own; play those by folder.
            uploads = [a for a in await assets.discover_assets(self.client) if a.kind == "sound" and a.is_upload]
            asset = next((a for a in uploads if notification.upload_for(a) == sound), None)
            if asset is None:
                raise
        await self.client.audio_play(
            stock_path=None if asset.is_upload else asset.reference,
            path=asset.reference if asset.is_upload else None,
            application_name=asset.application or APP_NAME,
            timeout=REQUEST_TIMEOUT,
        )
        self._step("play", f"play:{sound}")

    async def ask(self, agent: str, question: str, detail: str, timeout: int, color: str | None = None) -> str:
        """Wheel forward allows, wheel back or Back denies. Returns allow, deny or timeout."""
        await self.draw(ask_payload(agent, question, detail, timeout, self.cfg, color))
        if self.cfg.dry_run:
            return "timeout"
        async with Gestures(self.client) as gestures:
            gesture = await gestures.next(timeout)
        self._step("wheel", f"wheel:{gesture or 'timeout'}")
        return {"forward": "allow", "back": "deny", "cancel": "deny"}.get(gesture or "", "timeout")

    async def choose(self, agent: str, title: str, options: Sequence[str], timeout: int, color: str | None = None) -> str:
        """Wheel scrolls the options, resting picks one. Returns the label, cancel or timeout."""
        index, moved = 0, False
        await self.draw(choice_payload(agent, title, options, index, timeout, self.cfg, color))
        if self.cfg.dry_run:
            return "timeout"
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        async with Gestures(self.client) as gestures:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    self._step("wheel", "wheel:rest" if moved else "wheel:timeout")
                    return options[index] if moved else "timeout"
                gesture = await gestures.next(min(remaining, DWELL_SECONDS) if moved else remaining)
                if gesture is None:
                    self._step("wheel", "wheel:rest" if moved else "wheel:timeout")
                    return options[index] if moved else "timeout"
                self._step("wheel", f"wheel:{gesture}")
                if gesture == "cancel":
                    return "cancel"
                index = (index + (1 if gesture == "forward" else -1)) % len(options)
                moved = True
                await self.draw(choice_payload(agent, title, options, index, timeout, self.cfg, color))

    async def press(self, key: str) -> None:
        """Press a key from software: up and down are wheel steps; ok, back and start the buttons."""
        from busylib.types import InputKey

        if self.cfg.dry_run:
            print(json.dumps({"press": key}))
            self._step("input", f"input:{key}:dry-run")
            return
        await self.client.input(InputKey(key))
        self._step("input", f"input:{key}")

    async def sounds(self) -> list[tuple[str, str]]:
        """Every sound the bar can play, as (name to pass to --sound, file on the bar). Stock names first."""
        stock = [(name, path) for name, path in notification.STOCK_SOUNDS.items()]
        if self.cfg.dry_run:
            return stock
        found = []
        for asset in await assets.discover_assets(self.client):
            if asset.kind != "sound":
                continue
            name = asset.name if not asset.is_upload or asset.application == APP_NAME else notification.upload_for(asset)
            found.append((name, asset.device_path if asset.is_upload else asset.reference))
        known = {path for _, path in stock}
        return stock + sorted(pair for pair in found if pair[1] not in known)

    async def screen(self, display: int = 0) -> bytes:
        """The live pixels of the front (0, 72x16) or back (1, 160x80) display: RGB, three bytes each."""
        return await asyncio.wait_for(self.client.screen(display), REQUEST_TIMEOUT)

    async def snapshot(self) -> dict[str, Any]:
        """Firmware, power, link and the bar's own session, flat, for status and the panel."""
        info: dict[str, Any] = {"addr": self.cfg.addr}
        status = await self.client.api_request("GET", "/api/status", timeout=REQUEST_TIMEOUT)
        if isinstance(status, dict):
            system, firmware, power, device = ((status.get(key) or {}) for key in ("system", "firmware", "power", "device"))
            info.update(api=system.get("api_semver"), uptime=system.get("uptime"), firmware=firmware.get("version"),
                        battery=power.get("battery_charge"), power=power.get("state"), usb_mv=power.get("usb_voltage"),
                        serial=device.get("serial_number"))
        for key, path, pick in EXTRAS:
            try:
                data = await self.client.api_request("GET", path, timeout=REQUEST_TIMEOUT)
            except Exception:
                continue
            if isinstance(data, dict):
                info[key] = pick(data)
        return info

    async def summary(self) -> str:
        info = await self.snapshot()
        return (f"BUSY Bar at {self.cfg.addr}: API {info.get('api')}, firmware {info.get('firmware')}, "
                f"battery {info.get('battery')}% ({info.get('power')}), {info.get('transport') or 'unknown'} link, "
                f"bar session {str(info.get('busy') or 'unknown').lower()}")


def print_error(message: str) -> None:
    print(f"busybar-agents: {message}", file=sys.stderr)
