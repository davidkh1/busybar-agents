"""The ``busybar-agents`` command line.

    busybar-agents raise --agent claude --session 1a2b3c4d --project api --reason "needs permission"
    busybar-agents lower --agent claude --session 1a2b3c4d
    busybar-agents done  --agent claude --session 1a2b3c4d --project api
    busybar-agents ask   --question "ALLOW?" --detail "Bash: npm test"   # prints allow|deny|timeout
    busybar-agents hello --agent claude --project api                     # 4 s blip: ready
    busybar-agents status
    busybar-agents clear

Adapters for each coding agent translate that agent's hook events into these
verbs; the verbs are the same whoever is asking.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

from . import __version__
from .bar import Bar, done_payload, hands_payload, hello_payload, print_error
from .config import Config
from .state import Hand, HandsFile


def _add_identity(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--agent", default="agent", help="who is asking: claude, codex, gemini, ...")
    parser.add_argument("--session", default="default", help="short session id; one hand per session")
    parser.add_argument("--project", default=Path.cwd().name, help="shown on the bar; defaults to the cwd name")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="busybar-agents", description="Coding agents raise a hand on your BUSY Bar.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="show busylib logging")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("raise", help="put a hand up")
    _add_identity(p)
    p.add_argument("--reason", default="needs you", help="a few words: needs permission, waiting for you, ...")

    p = sub.add_parser("lower", help="take the hand down")
    _add_identity(p)

    p = sub.add_parser("done", help="lower the hand and show a short green DONE")
    _add_identity(p)
    p.add_argument("--message", default="DONE")

    p = sub.add_parser("hello", help="short blip that the bar is listening; no state change")
    _add_identity(p)

    p = sub.add_parser("ask", help="show a question, wait for the wheel, print allow|deny|timeout")
    _add_identity(p)
    p.add_argument("--question", default="ALLOW?")
    p.add_argument("--detail", default="")
    p.add_argument("--timeout", type=int, default=None, help="seconds; default BUSYBAR_ASK_TIMEOUT")

    sub.add_parser("clear", help="lower every hand and clear the bar")
    sub.add_parser("status", help="list raised hands and the bar's state")
    return parser


async def perform(args: argparse.Namespace, cfg: Config, hands_file: HandsFile, bar) -> str | None:
    """Apply one verb to the state file and the bar. ``bar`` needs draw, clear, play and ask."""
    if args.command == "raise":
        hands_file.prune(cfg.ttl)
        hand = Hand(agent=args.agent, session=args.session, project=args.project, reason=args.reason, since=time.time())
        hands = hands_file.raise_hand(hand)
        await bar.draw(hands_payload(hands, cfg))
        if cfg.sound:
            await bar.play(cfg.sound)
    elif args.command == "lower":
        removed, hands = hands_file.take(args.agent, args.session)
        if not removed:
            return None  # nothing of ours was up; a DONE may be showing, leave it
        if hands:
            await bar.draw(hands_payload(hands, cfg))
        else:
            await bar.clear()
    elif args.command == "done":
        hands_file.take(args.agent, args.session)
        hand = Hand(agent=args.agent, session=args.session, project=args.project, reason="done", since=time.time())
        await bar.draw(done_payload(hand, args.message, cfg))
    elif args.command == "hello":
        if cfg.hello_seconds > 0:
            await bar.draw(hello_payload(args.agent, args.project, cfg))
    elif args.command == "ask":
        timeout = args.timeout or cfg.ask_timeout
        answer = await bar.ask(args.agent, args.question, args.detail, timeout)
        hands = hands_file.prune(cfg.ttl)
        if hands:
            await bar.draw(hands_payload(hands, cfg))
        else:
            await bar.clear()
        return answer
    elif args.command == "clear":
        hands_file.clear()
        await bar.clear()
    return None


async def _run(args: argparse.Namespace, cfg: Config) -> int:
    hands_file = HandsFile(cfg.state_path)

    if args.command == "status":
        hands = hands_file.prune(cfg.ttl)
        if not hands:
            print("no hands up")
        for hand in hands:
            print(f"{hand.agent:8} {hand.session:10} {hand.project:24} {hand.reason:24} {int(hand.age)}s")
        try:
            async with Bar(cfg) as bar:
                print(await bar.summary())
        except Exception as err:  # the bar may simply be unplugged
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
    cfg = Config.from_env()
    try:
        return asyncio.run(_run(args, cfg))
    except KeyboardInterrupt:
        return 130
    except Exception as err:  # never a traceback in a hook's stderr
        print_error(f"{type(err).__name__}: {err}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
