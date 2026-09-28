"""The ``busybar-agents`` command line.

    busybar-agents raise  --agent claude --session 1a2b3c4d --project api --reason "permission?"
    busybar-agents lower  --agent claude --session 1a2b3c4d
    busybar-agents done   --agent claude --session 1a2b3c4d --project api
    busybar-agents ask    --question "ALLOW?" --detail "Bash: npm test"    # prints allow|deny|timeout
    busybar-agents choose --title Framework --option React --option Vue     # prints label|cancel|timeout
    busybar-agents hello  --agent claude --project api
    busybar-agents wheel  on | off | status                                  # answer from the wheel, every session
    busybar-agents status | redraw | clear

Adapters translate each agent's hook events into these verbs.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

from . import __version__
from .bar import Bar, done_payload, hands_payload, hello_payload, print_error
from .config import Config
from .state import Hand, HandsFile, WheelFile


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

    p = sub.add_parser("hello", help="short ready blip")
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


async def _run(args: argparse.Namespace, cfg: Config) -> int:
    hands_file = HandsFile(cfg.state_path)

    if args.command == "wheel":
        print(await perform(args, cfg, hands_file, None))
        return 0

    if args.command == "status":
        hands = hands_file.prune(cfg.ttl)
        if not hands:
            print("no hands up")
        for hand in hands:
            print(f"{hand.agent:8} {hand.session:10} {hand.project:24} {hand.reason:24} {int(hand.age)}s")
        try:
            async with Bar(cfg) as bar:
                print(await bar.summary())
        except Exception as err:
            print_error(f"bar not reachable at {cfg.addr}: {err}")
            return 1
        return 0

    async with Bar(cfg) as bar:
        answer = await perform(args, cfg, hands_file, bar)
    if answer is not None:
        print(answer)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.ERROR)
    if not args.verbose:
        logging.getLogger("busylib").setLevel(logging.ERROR)
    try:
        return asyncio.run(_run(args, Config.from_env()))
    except KeyboardInterrupt:
        return 130
    except Exception as err:  # hooks want one line, not a traceback
        print_error(f"{type(err).__name__}: {err}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
