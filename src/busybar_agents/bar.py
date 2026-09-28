"""Everything that touches the bar.

Payload builders are pure functions so they can be tested without hardware.
``Bar`` is the only place that talks to the device, through busylib.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
from typing import Sequence

from busylib import AsyncBusyBar, types
from busylib.features import notification

from .config import APP_NAME, Config
from .state import Hand
from .text import sanitize

StockIcon = notification.StockIcon

# Stock artwork every bar ships with; nothing has to be uploaded.
ICON_EYES = StockIcon("shared/images/dt_emoji_eyes.image", 16)
ICON_CHECK = StockIcon("shared/images/checkmark_front_8x8.image", 8)
ICON_DIALOG = StockIcon("shared/images/dt_dialog.image", 16)

# Text colour per agent, so a glance says who is asking. #RRGGBBAA.
AGENT_COLORS = {
    "claude": "#D97757FF",
    "codex": "#FFFFFFFF",
    "gemini": "#4C8DF6FF",
}
DEFAULT_COLOR = "#FFB000FF"

LED_RAISE = "#FF9900FF"
LED_DONE = "#00C853FF"
LED_ASK = "#2979FFFF"

REQUEST_TIMEOUT = 5.0  # seconds; a hook must never hang on an unplugged bar

SCROLL_START_DELAY_MS = 1500  # let the eye land on the first words before the marquee moves
SCROLL_REPEAT_DELAY_MS = 1200  # and rest again between cycles


def _calm_scroll(payload: types.DisplayElements) -> types.DisplayElements:
    """Pause long lines at their start and between cycles; busylib scrolls at once."""
    elements = []
    for element in payload.elements:
        if getattr(element, "scroll_rate", None):
            element = element.model_copy(
                update={"scroll_start_delay": SCROLL_START_DELAY_MS, "scroll_repeat_delay": SCROLL_REPEAT_DELAY_MS}
            )
        elements.append(element)
    return payload.model_copy(update={"elements": elements})


def hands_payload(hands: Sequence[Hand], cfg: Config) -> types.DisplayElements:
    """What the strip shows while at least one hand is up."""
    ordered = sorted(hands, key=lambda h: h.since)
    if len(ordered) == 1:
        hand = ordered[0]
        line_1 = sanitize(hand.agent.upper(), 12) or "AGENT"
        line_2 = sanitize(f"{hand.reason} - {hand.project}")
        color = AGENT_COLORS.get(hand.agent.lower(), DEFAULT_COLOR)
    else:
        line_1 = f"{len(ordered)} AGENTS"
        projects = list(dict.fromkeys(sanitize(h.project, 20) for h in ordered))
        line_2 = sanitize(", ".join(p for p in projects if p))
        color = DEFAULT_COLOR
    payload = notification.build_notification(
        line_1,
        line_2=line_2 or None,
        icon=ICON_EYES,
        line_1_font="bold",
        line_2_font="tiny",
        line_1_color=color,
        duration=cfg.ttl,
        priority=cfg.priority,
        application_name=APP_NAME,
    )
    return _calm_scroll(payload.model_copy(update={"led_notification_color": LED_RAISE}))


def done_payload(hand: Hand, message: str, cfg: Config) -> types.DisplayElements:
    """A short green confirmation when an agent finishes its turn."""
    payload = notification.build_notification(
        sanitize(message, 12) or "DONE",
        line_2=sanitize(f"{hand.agent}: {hand.project}") or None,
        icon=ICON_CHECK,
        line_1_font="bold",
        line_2_font="tiny",
        line_1_color=LED_DONE,
        duration=cfg.done_seconds,
        priority=cfg.priority,
        application_name=APP_NAME,
    )
    return _calm_scroll(payload.model_copy(update={"led_notification_color": LED_DONE}))


def ask_payload(question: str, detail: str, timeout: int, cfg: Config) -> types.DisplayElements:
    """A question the person answers with the wheel."""
    payload = notification.build_notification(
        sanitize(question, 12) or "ALLOW?",
        line_2=sanitize(detail) or None,
        icon=ICON_DIALOG,
        line_1_font="bold",
        line_2_font="tiny",
        line_1_color=DEFAULT_COLOR,
        duration=timeout,
        priority=cfg.priority,
        application_name=APP_NAME,
    )
    return _calm_scroll(payload.model_copy(update={"led_notification_color": LED_ASK}))


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

    async def draw(self, payload: types.DisplayElements) -> None:
        if self.cfg.dry_run:
            print(payload.model_dump_json(exclude_none=True, indent=2))
            return
        await self.client.display_draw(payload, application_name=APP_NAME, timeout=REQUEST_TIMEOUT)

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

    async def ask(self, question: str, detail: str, timeout: int) -> str:
        """Show a question and wait for a gesture. Returns allow, deny or timeout.

        Wheel forward means allow, wheel back or the Back button means deny.
        The bar's own UI still sees the gesture, so the wheel is chosen because
        it only moves a highlight, where Start would begin a session.
        """
        await self.draw(ask_payload(question, detail, timeout, self.cfg))
        if self.cfg.dry_run:
            return "timeout"
        try:
            return await asyncio.wait_for(self._wait_for_gesture(), timeout)
        except asyncio.TimeoutError:
            return "timeout"

    async def _wait_for_gesture(self) -> str:
        events = importlib.import_module("busylib.features.input_events")
        async for message in self.client.stream_status_ws():
            if not isinstance(message, dict):
                continue
            for event in events.input_events(message):
                if isinstance(event, events.EncoderEvent) and event.delta:
                    return "allow" if event.delta > 0 else "deny"
                if isinstance(event, events.ButtonEvent) and event.is_press and event.button == "back":
                    return "deny"
        return "timeout"

    async def summary(self) -> str:
        """One line about the bar, for ``status``."""
        version = await self.client.version()
        power = await self.client.status_power()
        return f"BUSY Bar at {self.cfg.addr}: API {version.api_semver}, battery {power.battery_charge}% ({power.state})"


def print_error(message: str) -> None:
    print(f"busybar-agents: {message}", file=sys.stderr)
