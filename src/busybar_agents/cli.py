"""The ``busybar-agents`` command line.

    busybar-agents raise  --agent claude --session 1a2b3c4d --project api --reason "permission?"
    busybar-agents lower  --agent claude --session 1a2b3c4d
    busybar-agents done   --agent claude --session 1a2b3c4d --project api
    busybar-agents ask    --question "ALLOW?" --detail "Bash: npm test"    # prints allow|deny|timeout
    busybar-agents choose --title Framework --option React --option Vue     # prints label|cancel|timeout
    busybar-agents hello  --agent claude --project api
    busybar-agents wheel  on | off | status                                  # answer from the wheel, every session
    busybar-agents status | redraw | clear
    busybar-agents log    [-n 40] [-f] [--json]                              # who fired what, what the bar said
    busybar-agents panel  [--port 8765]                                      # control panel in the browser

Adapters translate each agent's hook events into these verbs. Every verb
that touches the bar leaves one line in the event log.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

from . import __version__
from .bar import Bar, done_payload, hands_payload, hello_payload, print_error
from .config import Config
from .log import follow, format_event, log_path, read, record
from .state import Hand, HandsFile, WheelFile

# Arguments worth repeating in the event log.
NOTED = ("agent", "session", "project", "reason", "color", "question", "detail", "title", "option", "message", "timeout")


def _add_identity(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--agent", default="agent", help="claude, codex, ...")
    parser.add_argument("--session", default="default", help="short session id")
    parser.add_argument("--project", default=Path.cwd().name, help="session name or folder, shown on the bar")
    parser.add_argument("--color", default=None, help="session colour: a name like pink, or #RRGGBB; default is the agent's")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="busybar-agents", description="Coding agents raise a hand on your BUSY Bar.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="show busylib logging")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("raise", help="hand up")
    _add_identity(p)
    p.add_argument("--reason", default="needs you", help="a few words, e.g. permission?")

    p = sub.add_parser("lower", help="hand down")
    _add_identity(p)

    p = sub.add_parser("done", help="hand down, show DONE")
    _add_identity(p)
    p.add_argument("--message", default="DONE")

    p = sub.add_parser("hello", help="short READY blip with the session's name")
    _add_identity(p)

    p = sub.add_parser("ask", help="yes/no on the wheel; prints allow, deny or timeout")
    _add_identity(p)
    p.add_argument("--question", default="ALLOW?")
    p.add_argument("--detail", default="")
    p.add_argument("--timeout", type=int, default=None, help="seconds, default BUSYBAR_ASK_TIMEOUT")

    p = sub.add_parser("choose", help="pick one option with the wheel; prints the label, cancel or timeout")
    _add_identity(p)
    p.add_argument("--title", default="?", help="short title under the option")
    p.add_argument("--option", action="append", required=True, help="option label, repeatable")
    p.add_argument("--timeout", type=int, default=None, help="seconds, default BUSYBAR_ASK_TIMEOUT")

    p = sub.add_parser("wheel", help="answer permissions and questions from the wheel: on, off or status")
    p.add_argument("state", nargs="?", default="status", choices=["on", "off", "status"])

    sub.add_parser("redraw", help="draw the recorded hands again")
    sub.add_parser("clear", help="lower every hand, clear the bar")
    sub.add_parser("status", help="list hands and the bar's state")

    p = sub.add_parser("log", help="the event log: which process fired what, what was drawn, what the bar said")
    p.add_argument("-n", "--lines", type=int, default=40, help="how many of the latest events (default 40)")
    p.add_argument("-f", "--follow", action="store_true", help="keep printing new events")
    p.add_argument("--json", action="store_true", help="the raw JSON lines")

    p = sub.add_parser("panel", help="control panel in the browser: screens, hands, wheel, settings, log")
    p.add_argument("--host", default="127.0.0.1", help="listen address (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=8765, help="listen port (default 8765)")
    p.add_argument("--no-browser", action="store_true", help="do not open the page")
    return parser


async def perform(args: argparse.Namespace, cfg: Config, hands_file: HandsFile, bar) -> str | None:
    """Apply one verb. ``bar`` needs draw, clear, play, ask and choose."""
    hands_file.prune(cfg.ttl)
    if args.command == "raise":
        hand = Hand(agent=args.agent, session=args.session, project=args.project, reason=args.reason, since=time.time(), color=args.color)
        await bar.draw(hands_payload(hands_file.raise_hand(hand), cfg))
        if cfg.sound:
            await bar.play(cfg.sound)
    elif args.command == "lower":
        removed, hands = hands_file.take(args.agent, args.session)
        if not removed:
            return None  # nothing was up; leave the strip alone
        if hands:
            await bar.draw(hands_payload(hands, cfg))
        else:
            await bar.clear()
    elif args.command == "done":
        _, hands = hands_file.take(args.agent, args.session)
        if hands:
            await bar.draw(hands_payload(hands, cfg))  # others still waiting
        else:
            hand = Hand(agent=args.agent, session=args.session, project=args.project, reason="done", since=time.time(), color=args.color)
            await bar.draw(done_payload(hand, args.message, cfg))
    elif args.command == "hello":
        if cfg.hello_seconds > 0:
            await bar.draw(hello_payload(args.agent, args.project, cfg, args.color))
    elif args.command in ("ask", "choose"):
        timeout = args.timeout or cfg.ask_timeout
        if args.command == "ask":
            answer = await bar.ask(args.agent, args.question, args.detail, timeout, args.color)
        else:
            answer = await bar.choose(args.agent, args.title, args.option, timeout, args.color)
        hands = hands_file.prune(cfg.ttl)
        if hands:
            await bar.draw(hands_payload(hands, cfg))
        else:
            await bar.clear()
        return answer
    elif args.command == "wheel":
        return wheel_report(args.state, cfg)
    elif args.command == "redraw":
        hands = hands_file.load()
        if hands:
            await bar.draw(hands_payload(hands, cfg))
        else:
            await bar.clear()
    elif args.command == "clear":
        hands_file.clear()
        await bar.clear()
    return None


def wheel_report(state: str, cfg: Config) -> str:
    """Set or read the wheel switch; one line for the user."""
    wheel = WheelFile(cfg.wheel_path)
    current = wheel.write(state == "on") if state != "status" else wheel.read()
    line = "wheel on: ALLOW?, choices and GO? come to the bar" if current["ask"] or current["go"] else "wheel off: everything stays in the terminal"
    overrides = [name for name in ("BUSYBAR_ASK", "BUSYBAR_GO") if os.environ.get(name, "").strip()]
    if overrides:
        line += f"; {' and '.join(overrides)} in the environment wins until the agent restarts"
    return line


async def execute(args: argparse.Namespace, cfg: Config, src: str = "cli") -> str | None:
    """One verb against the bar, then one line in the event log, whatever happened."""
    bar = Bar(cfg)
    started = time.monotonic()
    answer = error = None
    try:
        async with bar:
            answer = await perform(args, cfg, HandsFile(cfg.state_path), bar)
        return answer
    except Exception as err:
        error = f"{type(err).__name__}: {err}"
        raise
    finally:
        note(cfg, args, src, started, answer, error, bar.trail)


def note(cfg: Config, args: argparse.Namespace, src: str, started: float, answer: str | None, error: str | None, trail: list) -> None:
    """The log line for one verb: its arguments, the steps taken on the bar, the last words drawn, the answer."""
    draws = [step for step in trail if step["op"] == "draw"]
    shown = draws[0] if args.command in ("ask", "choose") and draws else draws[-1] if draws else None  # the question, not the board redrawn after it
    record(
        log_path(cfg.state_path),
        src=src,
        trace=os.environ.get("BUSYBAR_TRACE") or None,
        verb=args.command,
        **{key: value for key, value in vars(args).items() if key in NOTED and value not in (None, "", [])},
        ms=int((time.monotonic() - started) * 1000),
        bar=[step["note"] for step in trail] or None,
        shown=shown["texts"] if shown else None,
        result=answer,
        error=error,
        addr=cfg.addr,
        payload=shown["payload"] if shown else None,
    )


async def status(cfg: Config) -> int:
    hands = HandsFile(cfg.state_path).prune(cfg.ttl)
    if not hands:
        print("no hands up")
    for hand in hands:
        print(f"{hand.agent:8} {hand.session:10} {hand.project:24} {hand.reason:24} {int(hand.age)}s")
    wheel = WheelFile(cfg.wheel_path).read()
    print(f"wheel {'on' if wheel['ask'] or wheel['go'] else 'off'}; log {log_path(cfg.state_path)}")
    try:
        async with Bar(cfg) as bar:
            print(await bar.summary())
    except Exception as err:
        print_error(f"bar not reachable at {cfg.addr}: {err}")
        return 1
    return 0


def show_log(args: argparse.Namespace, cfg: Config) -> int:
    path = log_path(cfg.state_path)
    events = read(path, args.lines)
    if not events and not args.follow:
        print(f"no events yet in {path}")
        return 0
    for event in events:
        print(json.dumps(event) if args.json else format_event(event))
    if args.follow:
        for event in follow(path):
            print(json.dumps(event) if args.json else format_event(event), flush=True)
    return 0


async def _run(args: argparse.Namespace, cfg: Config) -> int:
    if args.command == "wheel":
        print(await perform(args, cfg, HandsFile(cfg.state_path), None))
        return 0
    if args.command == "status":
        return await status(cfg)
    answer = await execute(args, cfg)
    if answer is not None:
        print(answer)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.ERROR)
    if not args.verbose:
        logging.getLogger("busylib").setLevel(logging.ERROR)
    try:
        cfg = Config.from_env()
        if args.command == "log":
            return show_log(args, cfg)
        if args.command == "panel":
            from .panel import serve

            return serve(cfg, host=args.host, port=args.port, open_browser=not args.no_browser)
        return asyncio.run(_run(args, cfg))
    except KeyboardInterrupt:
        return 130
    except Exception as err:  # hooks want one line, not a traceback
        print_error(f"{type(err).__name__}: {err}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
