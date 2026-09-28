"""Everything that touches the bar.

Payload builders are pure functions that return the JSON the bar's draw API
takes, so they can be tested without hardware. ``Bar`` is the only place that
talks to the device, through busylib.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
from typing import Any, Sequence

from busylib import AsyncBusyBar
from busylib.features import notification

from .config import APP_NAME, Config
from .state import Hand
from .text import sanitize

# Anthropic's palette, as #RRGGBBAA. Claude speaks in Claude orange.
CLAUDE_ORANGE = "#D97757FF"
IVORY = "#F0EEE6FF"
AGENT_COLORS = {
    "claude": CLAUDE_ORANGE,
    "codex": "#FFFFFFFF",
    "gemini": "#4C8DF6FF",
}
DEFAULT_COLOR = "#FFB000FF"

# The front strip is 72x16. A 16 px icon sits at the left edge, text follows.
FRONT_WIDTH = 72
ICON_WIDTH = 16
TEXT_X = ICON_WIDTH + 2
TEXT_WIDTH = FRONT_WIDTH - TEXT_X
SCROLL_THRESHOLD_CHARS = {"bold": 8, "tiny": 12}  # what fits beside the icon, per font
SCROLL_RATE = 1200  # pixels per minute
SCROLL_START_DELAY_MS = 1500  # let the eye land on the first words first
SCROLL_REPEAT_DELAY_MS = 1200

REQUEST_TIMEOUT = 5.0  # seconds; a hook must never hang on an unplugged bar
DWELL_SECONDS = 2.5  # rest this long on a choice and it is taken

# Icons are XPM2 bitmaps drawn inline: no upload, no extra files, and the
# element keeps one type, which the firmware insists on for a reused id.
# Clawd is the Claude Code mascot, 16x10, with white eyes.
CLAWD = {
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
    "up": [  # right arm raised
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
    "done": [  # happy, eyes closed
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
# Every other agent: a terminal prompt in its own colour.
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


def xpm(rows: Sequence[str], colors: dict[str, str]) -> str:
    """Rows of characters plus a colour per character, as XPM2 text."""
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise ValueError("bitmap rows differ in width")
    header = ["! XPM2", f"{width} {len(rows)} {len(colors)} 1"]
    header += [f"{char} c {value}" for char, value in colors.items()]
    return "\n".join([*header, *rows])


def icon_element(agent: str, timeout: int, mood: str = "ready") -> dict[str, Any]:
    color = AGENT_COLORS.get(agent.lower(), DEFAULT_COLOR)[:7]
    if agent.lower() == "claude":
        data = xpm(CLAWD[mood], {".": "none", "o": color, "w": "#FFFFFF"})
    else:
        data = xpm(PROMPT_GLYPH, {".": "none", "o": color})
    return {
        "id": "10",
        "type": "xpmbitmap",
        "x": 0,
        "y": 8,
        "align": "mid_left",
        "display": "front",
        "timeout": timeout,
        "data": data,
    }


def text_element(element_id: str, text: str, font: str, color: str, y: int, align: str, timeout: int) -> dict[str, Any]:
    element: dict[str, Any] = {
        "id": element_id,
        "type": "text",
        "x": TEXT_X,
        "y": y,
        "align": align,
        "display": "front",
        "timeout": timeout,
        "text": text,
        "font": font,
        "color": color,
    }
    if len(text) > SCROLL_THRESHOLD_CHARS.get(font, 12):
        element.update(
            width=TEXT_WIDTH,
            scroll_rate=SCROLL_RATE,
            scroll_start_delay=SCROLL_START_DELAY_MS,
            scroll_repeat_delay=SCROLL_REPEAT_DELAY_MS,
        )
    return element


def notice(agent: str, line_1: str, line_2: str, timeout: int, cfg: Config, mood: str = "ready") -> dict[str, Any]:
    """Icon, a bold word in the agent's colour, and a small line under it."""
    color = AGENT_COLORS.get(agent.lower(), DEFAULT_COLOR)
    elements = [
        icon_element(agent, timeout, mood),
        text_element("11", sanitize(line_1, 12) or "AGENT", "bold", color, -1, "top_left", timeout),
    ]
    detail = sanitize(line_2)
    if detail:
        elements.append(text_element("12", detail, "tiny", IVORY, 15, "bottom_left", timeout))
    return {
        "application_name": APP_NAME,
        "priority": cfg.priority,
        "led_notification_color": color,
        "elements": elements,
    }


def hands_payload(hands: Sequence[Hand], cfg: Config) -> dict[str, Any]:
    """What the strip shows while at least one hand is up."""
    ordered = sorted(hands, key=lambda h: h.since)
    if len(ordered) == 1:
        hand = ordered[0]
        return notice(hand.agent, hand.agent.upper(), f"{hand.reason} - {hand.project}", cfg.ttl, cfg, mood="up")
    agents = {h.agent.lower() for h in ordered}
    agent = ordered[0].agent if len(agents) == 1 else "agents"
    projects = ", ".join(dict.fromkeys(sanitize(h.project, 20) for h in ordered))
    return notice(agent, f"{len(ordered)} AGENTS", projects, cfg.ttl, cfg, mood="up")


def done_payload(hand: Hand, message: str, cfg: Config) -> dict[str, Any]:
    """A short confirmation when an agent finishes its turn."""
    return notice(hand.agent, message, hand.project, cfg.done_seconds, cfg, mood="done")


def hello_payload(agent: str, project: str, cfg: Config) -> dict[str, Any]:
    """A blip when a session starts: the bar is listening to this agent."""
    return notice(agent, agent.upper(), "ready", max(1, cfg.hello_seconds), cfg)


def choice_payload(agent: str, title: str, options: Sequence[str], index: int, timeout: int, cfg: Config) -> dict[str, Any]:
    """One option at a time, big, with its position and the question's short title."""
    return notice(agent, options[index], f"{index + 1}/{len(options)} {title}", timeout, cfg, mood="up")


def ask_payload(agent: str, question: str, detail: str, timeout: int, cfg: Config) -> dict[str, Any]:
    """A question the person answers with the wheel."""
    return notice(agent, question, detail, timeout, cfg, mood="up")


def texts(payload: dict[str, Any]) -> list[str]:
    """The words a payload shows, in order. Handy for tests and dry runs."""
    return [e["text"] for e in payload["elements"] if e.get("text")]


class Gestures:
    """Physical input from the bar as a queue of ``forward``, ``back`` and ``cancel``."""

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
        except Exception as err:  # the stream dropped; the caller simply times out
            print_error(f"input stream ended: {type(err).__name__}: {err}")

    async def next(self, timeout: float) -> str | None:
        try:
            return await asyncio.wait_for(self.queue.get(), timeout)
        except asyncio.TimeoutError:
            return None


class Bar:
    """An open connection to one bar. Use as ``async with Bar(cfg) as bar``."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.client = AsyncBusyBar(cfg.addr, token=cfg.token)

    async def __aenter__(self) -> "Bar":
        await self.client.__aenter__()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.client.__aexit__(*exc)

    async def draw(self, payload: dict[str, Any]) -> None:
        if self.cfg.dry_run:
            print(json.dumps(payload, indent=2))
            return
        try:
            await self.client.api_request("POST", "/api/display/draw", json_payload=payload, timeout=REQUEST_TIMEOUT)
        except Exception as err:
            if "409" not in str(err):
                raise
            # A focus session is running and outranks us. Stay quiet: that is
            # what a focus session is for. BUSYBAR_PRIORITY=91 breaks through.
            print_error("not drawn: a focus session is running (BUSYBAR_PRIORITY=91 overrides)")

    async def clear(self) -> None:
        if self.cfg.dry_run:
            print(json.dumps({"clear": APP_NAME}))
            return
        await self.client.display_clear(application_name=APP_NAME, timeout=REQUEST_TIMEOUT)

    async def play(self, sound: str) -> None:
        """Play a stock sound by its short name, e.g. ``reminder`` or ``event``."""
        if self.cfg.dry_run:
            print(json.dumps({"play": sound}))
            return
        asset = await notification.resolve_sound(self.client, sound, application_name=APP_NAME)
        await self.client.audio_play(
            stock_path=None if asset.is_upload else asset.reference,
            path=asset.reference if asset.is_upload else None,
            application_name=APP_NAME,
            timeout=REQUEST_TIMEOUT,
        )

    async def ask(self, agent: str, question: str, detail: str, timeout: int) -> str:
        """Show a question and wait for a gesture. Returns allow, deny or timeout.

        Wheel forward means allow, wheel back or the Back button means deny.
        The bar's own UI still sees the gesture, so the wheel is chosen because
        it only moves a highlight, where Start would begin a session.
        """
        await self.draw(ask_payload(agent, question, detail, timeout, self.cfg))
        if self.cfg.dry_run:
            return "timeout"
        async with Gestures(self.client) as gestures:
            gesture = await gestures.next(timeout)
        return {"forward": "allow", "back": "deny", "cancel": "deny"}.get(gesture or "", "timeout")

    async def choose(self, agent: str, title: str, options: Sequence[str], timeout: int) -> str:
        """Scroll through options with the wheel; rest on one to pick it.

        Returns the chosen label, ``cancel`` for the Back button, or ``timeout``
        when the wheel never moved.
        """
        index, moved = 0, False
        await self.draw(choice_payload(agent, title, options, index, timeout, self.cfg))
        if self.cfg.dry_run:
            return "timeout"
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        async with Gestures(self.client) as gestures:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return options[index] if moved else "timeout"
                gesture = await gestures.next(min(remaining, DWELL_SECONDS) if moved else remaining)
                if gesture is None:
                    return options[index] if moved else "timeout"
                if gesture == "cancel":
                    return "cancel"
                index = (index + (1 if gesture == "forward" else -1)) % len(options)
                moved = True
                await self.draw(choice_payload(agent, title, options, index, timeout, self.cfg))

    async def summary(self) -> str:
        """One line about the bar, for ``status``."""
        version = await self.client.version()
        power = await self.client.status_power()
        return f"BUSY Bar at {self.cfg.addr}: API {version.api_semver}, battery {power.battery_charge}% ({power.state})"


def print_error(message: str) -> None:
    print(f"busybar-agents: {message}", file=sys.stderr)
