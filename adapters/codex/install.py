#!/usr/bin/env python3
"""Add the BUSY Bar hooks to Codex CLI, or remove them again.

    python3 adapters/codex/install.py              # merge into ~/.codex/hooks.json
    python3 adapters/codex/install.py --uninstall  # take ours out, keep the rest
    python3 adapters/codex/install.py --print      # show the JSON without writing

Existing hooks in the file are kept. Ours are recognised by the path of
hook.py in their command, so running this again after moving the repo just
updates the path. Codex trusts hooks per definition: after installing, open
Codex and run /hooks to trust them.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "hook.py"
COMMAND = f'python3 "{HOOK}"'


def our_hooks() -> dict:
    def handler(**extra):
        return {"type": "command", "command": COMMAND, **extra}

    # Everything runs in the foreground: Codex 0.144 skips hooks marked async
    # ("async hooks are not supported yet"), and each call takes well under a second.
    return {
        "SessionStart": [{"matcher": "startup|resume", "hooks": [handler(timeout=20)]}],
        "UserPromptSubmit": [{"hooks": [handler(timeout=20)]}],
        "PermissionRequest": [{"hooks": [handler(timeout=40)]}],
        "PostToolUse": [{"hooks": [handler(timeout=20)]}],
        "Stop": [{"hooks": [handler(timeout=45)]}],
        "Interrupt": [{"hooks": [handler(timeout=3)]}],
        "SessionEnd": [{"hooks": [handler(timeout=3)]}],
    }


def hooks_file() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "hooks.json"


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {"hooks": {}}
    if not isinstance(data, dict):
        raise SystemExit(f"{path} is not a JSON object")
    data.setdefault("hooks", {})
    return data


def is_ours(entry: dict) -> bool:
    return any(str(HOOK) in str(h.get("command", "")) or "busybar-agents" in str(h.get("command", "")) for h in entry.get("hooks", []))


def strip_ours(hooks: dict) -> None:
    for event in list(hooks):
        kept = [e for e in hooks[event] if not is_ours(e)]
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--print", action="store_true", dest="show")
    args = parser.parse_args()

    ours = our_hooks()
    if args.show:
        print(json.dumps({"hooks": ours}, indent=2))
        return 0

    path = hooks_file()
    data = load(path)
    strip_ours(data["hooks"])
    if not args.uninstall:
        for event, entries in ours.items():
            data["hooks"].setdefault(event, []).extend(entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    if args.uninstall:
        print(f"removed the BUSY Bar hooks from {path}")
    else:
        print(f"wrote {path}\nNext: start codex, type /hooks, and trust the busybar-agents hooks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
